#include "wifi_audio.h"
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <sys/socket.h>
#include "lwip/inet.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "cJSON.h"
#include "esp_random.h"

static wifi_audio_read_t capture;
static wifi_audio_write_t playback;
static volatile int client_fd=-1;
static volatile bool mic_busy, has_ip;
static volatile bool requested, host_ready, host_wake;
// DAN4 extension: device advertises bit 32; host bit 16 owns transition cues.
// Cue destination is latched with intent, so a disconnect cannot move an end cue.
static bool host_cues, local_cue=true;
static uint32_t boot_id, revision;
static portMUX_TYPE state_lock=portMUX_INITIALIZER_UNLOCKED;
static volatile TickType_t last_control;
static volatile unsigned long sent_bytes,received_bytes;
static esp_netif_t *netif;
static char ssid[33],password[65],pair_key[33];
static bool configured;
static int last_disconnect;

bool wifi_audio_active(void){return client_fd>=0;}
bool wifi_audio_requested(void){return requested;}
bool wifi_audio_requested_with_cue(bool *local){
    portENTER_CRITICAL(&state_lock);
    bool value=requested;*local=local_cue;
    portEXIT_CRITICAL(&state_lock);
    return value;
}
bool wifi_audio_ready(void){return requested&&host_ready&&client_fd>=0&&(xTaskGetTickCount()-last_control)<pdMS_TO_TICKS(1000);}
static bool capture_allowed(void){return wifi_audio_ready()||(!requested&&host_wake&&client_fd>=0&&(xTaskGetTickCount()-last_control)<pdMS_TO_TICKS(1000));}
void wifi_audio_set_requested(bool enabled){
    portENTER_CRITICAL(&state_lock);
    if(requested!=enabled){
        local_cue=!host_cues||client_fd<0||(xTaskGetTickCount()-last_control)>=pdMS_TO_TICKS(1000);
        requested=enabled;revision++;host_ready=false;host_wake=false;
    }
    portEXIT_CRITICAL(&state_lock);
}
static bool send_all(int fd,const void *data,size_t len){
    const uint8_t *p=data;
    while(len){int n=send(fd,p,len,0);if(n<=0)return false;p+=n;len-=n;}
    return true;
}
static bool recv_all(int fd,void *data,size_t len){
    uint8_t *p=data;
    while(len){int n=recv(fd,p,len,0);if(n<=0)return false;p+=n;len-=n;}
    return true;
}
static void mic_task(void *arg){
    uint8_t packet[972];uint8_t *pcm=packet+12;
    while(1){
        int fd=client_fd;
        if(fd<0){mic_busy=false;vTaskDelay(pdMS_TO_TICKS(10));continue;}
        mic_busy=true;
        size_t got=0;
        memset(pcm,0,960);
        if(capture(pcm,960,&got,NULL)!=ESP_OK||!got){vTaskDelay(1);continue;}
        // Local wake detection is separately authorized; cloud readiness stays OFF.
        if(!capture_allowed())memset(pcm,0,960);
        uint32_t header[3];
        portENTER_CRITICAL(&state_lock);
        header[0]=(requested?1:0)|32;header[1]=boot_id;header[2]=revision;
        portEXIT_CRITICAL(&state_lock);
        if(!capture_allowed())memset(pcm,0,960);
        memcpy(packet,header,12);
        if(!send_all(fd,packet,sizeof(packet))){shutdown(fd,SHUT_RDWR);vTaskDelay(pdMS_TO_TICKS(10));}
        else sent_bytes+=960;
    }
}
static void server_task(void *arg){
    int server=socket(AF_INET,SOCK_STREAM,IPPROTO_IP);
    if(server<0)vTaskDelete(NULL);
    int yes=1;setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
    struct sockaddr_in addr={.sin_family=AF_INET,.sin_port=htons(48800),.sin_addr.s_addr=htonl(INADDR_ANY)};
    if(bind(server,(struct sockaddr*)&addr,sizeof(addr))<0||listen(server,1)<0){close(server);vTaskDelete(NULL);}
    while(1){
        int fd=accept(server,NULL,NULL);if(fd<0){vTaskDelay(pdMS_TO_TICKS(100));continue;}
        struct timeval timeout={.tv_sec=3};
        setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
        setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
        setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof(yes));
        char hello[36];
        if(!configured||!recv_all(fd,hello,36)||memcmp(hello,"DAN4",4)||memcmp(hello+4,pair_key,32)){
            shutdown(fd,SHUT_RDWR);close(fd);continue;
        }
        host_ready=false;host_wake=false;host_cues=false;
        if(!send_all(fd,"OKF4",4)){close(fd);continue;}
        client_fd=fd;
        uint8_t packet[972];uint8_t *pcm=packet+12;
        while(recv_all(fd,packet,sizeof(packet))){
            uint32_t header[3];memcpy(header,packet,12);
            portENTER_CRITICAL(&state_lock);
            if(header[1]==boot_id&&header[2]==revision){
                host_cues=(header[0]&16)!=0;
                if(header[0]&6){bool target=(header[0]&4)!=0;if(target!=requested){local_cue=!host_cues;requested=target;revision++;}}
                host_ready=requested&&(header[0]&1);last_control=xTaskGetTickCount();
                host_wake=!requested&&(header[0]&8);
            }
            portEXIT_CRITICAL(&state_lock);
            if(!wifi_audio_ready())memset(pcm,0,960);
            playback(pcm,960,NULL);received_bytes+=960;
        }
        client_fd=-1;host_ready=false;host_wake=false;shutdown(fd,SHUT_RDWR);
        while(mic_busy)vTaskDelay(pdMS_TO_TICKS(10));
        close(fd);
    }
}
static void event_handler(void *arg,esp_event_base_t base,int32_t id,void *data){
    if(base==IP_EVENT&&id==IP_EVENT_STA_GOT_IP){has_ip=true;last_disconnect=0;}
    if(base==WIFI_EVENT&&id==WIFI_EVENT_STA_DISCONNECTED){
        has_ip=false;last_disconnect=((wifi_event_sta_disconnected_t*)data)->reason;
        if(configured)esp_wifi_connect();
    }
}
static esp_err_t connect_config(void){
    wifi_config_t cfg={0};
    memcpy(cfg.sta.ssid,ssid,strlen(ssid));memcpy(cfg.sta.password,password,strlen(password));
    cfg.sta.threshold.authmode=WIFI_AUTH_WPA2_PSK;
    cfg.sta.pmf_cfg.capable=true;
    esp_err_t e=esp_wifi_set_config(WIFI_IF_STA,&cfg);if(e)return e;
    configured=true;return esp_wifi_connect();
}
void wifi_audio_init(wifi_audio_read_t read_cb,wifi_audio_write_t write_cb){
    capture=read_cb;playback=write_cb;
    boot_id=esp_random();requested=false;host_ready=false;revision=0;
    esp_err_t e=nvs_flash_init();
    // Preserve original NVS; never auto-erase if initialization fails.
    if(e!=ESP_OK)return;
    nvs_handle_t n;
    if(nvs_open("dan_wifi",NVS_READONLY,&n)==ESP_OK){
        size_t a=sizeof(ssid),b=sizeof(password),c=sizeof(pair_key);
        nvs_get_str(n,"ssid",ssid,&a);nvs_get_str(n,"pass",password,&b);nvs_get_str(n,"key",pair_key,&c);nvs_close(n);
    }
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    netif=esp_netif_create_default_wifi_sta();
    esp_netif_set_hostname(netif,"dan-atom");
    wifi_init_config_t config=WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&config));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,event_handler,NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,event_handler,NULL));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    if(ssid[0]&&strlen(pair_key)==32)connect_config();
    xTaskCreate(server_task,"dan_tcp",4096,NULL,6,NULL);
    xTaskCreate(mic_task,"dan_mic",4096,NULL,6,NULL);
}
esp_err_t wifi_audio_configure(const char *json){
    cJSON *obj=cJSON_Parse(json);if(!obj)return ESP_ERR_INVALID_ARG;
    cJSON *s=cJSON_GetObjectItem(obj,"ssid"),*p=cJSON_GetObjectItem(obj,"password"),*k=cJSON_GetObjectItem(obj,"key");
    if(!cJSON_IsString(s)||!cJSON_IsString(p)||!cJSON_IsString(k)||strlen(s->valuestring)>32||strlen(p->valuestring)>64||strlen(k->valuestring)!=32){cJSON_Delete(obj);return ESP_ERR_INVALID_ARG;}
    configured=false;esp_wifi_disconnect();
    strlcpy(ssid,s->valuestring,sizeof(ssid));strlcpy(password,p->valuestring,sizeof(password));strlcpy(pair_key,k->valuestring,sizeof(pair_key));cJSON_Delete(obj);
    nvs_handle_t n;esp_err_t e=nvs_open("dan_wifi",NVS_READWRITE,&n);if(e)return e;
    e=nvs_set_str(n,"ssid",ssid);if(!e)e=nvs_set_str(n,"pass",password);if(!e)e=nvs_set_str(n,"key",pair_key);if(!e)e=nvs_commit(n);nvs_close(n);
    return e?e:connect_config();
}
void wifi_audio_status(char *out,size_t size){
    esp_netif_ip_info_t ip={0};if(netif)esp_netif_get_ip_info(netif,&ip);
    snprintf(out,size,"WIFI configured=%d connected=%d ip=" IPSTR " reason=%d client=%d mic_bytes=%lu speaker_bytes=%lu requested=%d ready=%d boot=%lu revision=%lu\r\n",configured,has_ip,IP2STR(&ip.ip),last_disconnect,client_fd>=0,sent_bytes,received_bytes,requested,wifi_audio_ready(),(unsigned long)boot_id,(unsigned long)revision);
}
void wifi_audio_scan(char *out,size_t size){
    wifi_scan_config_t cfg={0};esp_err_t e=esp_wifi_scan_start(&cfg,true);
    if(e){snprintf(out,size,"SCAN error=%d\r\n",e);return;}
    wifi_ap_record_t aps[16];uint16_t count=16;esp_wifi_scan_get_ap_records(&count,aps);
    size_t used=snprintf(out,size,"SCAN count=%u\r\n",count);
    for(int i=0;i<count&&used+80<size;i++)used+=snprintf(out+used,size-used,"SSID=%s channel=%u rssi=%d\r\n",aps[i].ssid,aps[i].primary,aps[i].rssi);
}
