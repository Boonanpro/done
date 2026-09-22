#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/i2c.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_system.h"
#include "esp_rom_sys.h"
#include "soc/rtc_cntl_reg.h"
#include "usb_device_uac.h"
#include "tusb.h"
#include "wifi_audio.h"
#include "cue_sound.h"

static i2s_chan_handle_t tx, rx;
static SemaphoreHandle_t tx_lock;
static volatile bool ready, muted;
static volatile int gain_q15 = 32767, requested_volume = 100;
static volatile uint32_t usb_bytes, usb_peak, tx_peak, mic_peak, write_errors;
static volatile uint32_t mic_samples, mic_clipped;
static esp_err_t init_result;
static volatile TickType_t notification_until;
static volatile bool cue_pending;
static uint32_t cue_started[3],cue_completed[3],cue_errors,cue_max_wait_ms;

static esp_err_t reg_write(uint8_t reg, uint8_t value) {
    uint8_t data[] = {reg, value};
    return i2c_master_write_to_device(I2C_NUM_0, 0x18, data, 2, pdMS_TO_TICKS(100));
}
static int reg_read(uint8_t reg) {
    uint8_t value = 0;
    esp_err_t e = i2c_master_write_read_device(I2C_NUM_0, 0x18, &reg, 1, &value, 1, pdMS_TO_TICKS(100));
    return e == ESP_OK ? value : -1;
}
static esp_err_t audio_init(void) {
    i2c_config_t ic = {.mode=I2C_MODE_MASTER,.sda_io_num=45,.scl_io_num=0,
        .sda_pullup_en=true,.scl_pullup_en=true,.master.clk_speed=100000};
    esp_err_t e = i2c_param_config(I2C_NUM_0,&ic); if(e) return e;
    e=i2c_driver_install(I2C_NUM_0,ic.mode,0,0,0); if(e) return e;
    i2s_chan_config_t cc=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
    cc.dma_desc_num=8; cc.dma_frame_num=240; cc.auto_clear=true;
    e=i2s_new_channel(&cc,&tx,&rx); if(e) return e;
    i2s_std_config_t sc={
        .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(48000),
        .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_STEREO),
        .gpio_cfg={.mclk=I2S_GPIO_UNUSED,.bclk=17,.ws=3,.dout=48,.din=4},
    };
    e=i2s_channel_init_std_mode(tx,&sc); if(e) return e;
    e=i2s_channel_init_std_mode(rx,&sc); if(e) return e;
    e=i2s_channel_enable(tx); if(e) return e;
    e=i2s_channel_enable(rx); if(e) return e;
    // ES8311: BCLK*8 clock, 16-bit Philips I2S, ADC and DAC enabled.
    // Unity DAC gain: +32 dB was loud enough but user reported severe clipping.
    const uint8_t regs[][2]={
        {0x44,0x08},{0x44,0x08},{0x00,0x80},{0x01,0xbf},{0x02,0x18},
        {0x03,0x10},{0x04,0x10},{0x05,0x00},{0x06,0x03},{0x07,0x00},{0x08,0xff},
        {0x09,0x0c},{0x0a,0x0c},{0x0b,0x00},{0x0c,0x00},{0x0d,0x01},
        {0x0e,0x02},{0x10,0x1f},{0x11,0x7f},{0x12,0x00},{0x13,0x10},
        // Analog microphone PGA: +18 dB (6 * 3 dB), previously 0 dB.
        {0x14,0x16},{0x16,0x24},{0x17,0xbf},{0x1b,0x0a},{0x1c,0x6a},
        {0x31,0x00},{0x32,0xbf},{0x37,0x08},
    };
    for(size_t i=0;i<sizeof(regs)/sizeof(regs[0]);i++) {
        e=reg_write(regs[i][0],regs[i][1]); if(e) return e;
    }
    gpio_config_t amp={.pin_bit_mask=1ULL<<18,.mode=GPIO_MODE_INPUT_OUTPUT};
    e=gpio_config(&amp); if(e) return e;
    gpio_set_level(18,1);
    return reg_read(0x32)==0xbf ? ESP_OK : ESP_FAIL;
}
static esp_err_t output_cb(uint8_t *buf,size_t len,void *ctx) {
    (void)ctx;
    if(!ready||cue_pending) return ESP_OK;
    const int16_t *src=(const int16_t*)buf;
    usb_bytes+=len;
    if(xSemaphoreTake(tx_lock,pdMS_TO_TICKS(20))!=pdTRUE) return ESP_OK;
    if(cue_pending){xSemaphoreGive(tx_lock);return ESP_OK;}
    int16_t stereo[480];
    for(size_t pos=0;pos<len/2;) {
        size_t n=len/2-pos; if(n>240)n=240;
        int gain=muted?0:gain_q15;
        for(size_t i=0;i<n;i++) {
            int value=src[pos+i]; unsigned peak=value<0?-value:value;
            if(peak>usb_peak)usb_peak=peak;
            value=(value*gain)/32767; peak=value<0?-value:value;
            if(peak>tx_peak)tx_peak=peak;
            stereo[i*2]=stereo[i*2+1]=(int16_t)value;
        }
        size_t written=0;
        esp_err_t e=i2s_channel_write(tx,stereo,n*4,&written,100);
        if(e || written!=n*4)write_errors++;
        pos+=n;
    }
    xSemaphoreGive(tx_lock);
    return ESP_OK;
}
static esp_err_t input_cb(uint8_t *buf,size_t len,size_t *bytes_read,void *ctx) {
    (void)ctx;
    *bytes_read=0;
    if(!ready){memset(buf,0,len);*bytes_read=len;return ESP_OK;}
    int16_t stereo[480], *dst=(int16_t*)buf;
    while(*bytes_read<len) {
        size_t samples=(len-*bytes_read)/2;if(samples>240)samples=240;
        size_t got=0;
        esp_err_t e=i2s_channel_read(rx,stereo,samples*4,&got,30);
        if(e || got==0)break;
        for(size_t i=0;i<got/4;i++) {
            int v=stereo[i*2]; unsigned peak=v<0?-v:v;
            if(peak>mic_peak)mic_peak=peak;
            mic_samples++;if(peak>=32700)mic_clipped++;
            dst[*bytes_read/2+i]=(xTaskGetTickCount()<notification_until)?0:v;
        }
        *bytes_read+=got/2;
    }
    return ESP_OK;
}
// USB is power/provisioning only in the Wi-Fi firmware. Host UAC settings
// must never silence the independent Wi-Fi speaker after plugging in USB.
static void mute_cb(uint32_t value,void *ctx){(void)value;(void)ctx;}
static void volume_cb(uint32_t value,void *ctx){
    (void)value;(void)ctx;
}
static void cdc_message(const char *s){
    if(tud_cdc_connected()){tud_cdc_write_str(s);tud_cdc_write_flush();}
}
static esp_err_t usb_input_cb(uint8_t *b,size_t n,size_t *got,void *ctx){
    if(wifi_audio_active()||!wifi_audio_ready()){memset(b,0,n);*got=n;vTaskDelay(pdMS_TO_TICKS(10));return ESP_OK;}
    return input_cb(b,n,got,ctx);
}
static esp_err_t usb_output_cb(uint8_t *b,size_t n,void *ctx){
    return (wifi_audio_active()||!wifi_audio_ready())?ESP_OK:output_cb(b,n,ctx);
}
static void diagnostics(void){
    char line[384];
    snprintf(line,sizeof(line),"DAN_AUDIO ready=%d init=%d volume=%d gain=%d mute=%d usb_bytes=%lu usb_peak=%lu tx_peak=%lu mic_peak=%lu errors=%lu DAC=%02x CLK=%02x SDPIN=%02x AMP=%d\r\n",
        ready,init_result,requested_volume,gain_q15,muted,(unsigned long)usb_bytes,
        (unsigned long)usb_peak,(unsigned long)tx_peak,(unsigned long)mic_peak,
        (unsigned long)write_errors,reg_read(0x32),reg_read(1),reg_read(9),gpio_get_level(18));
    cdc_message(line);
    snprintf(line,sizeof(line),"MIC PGA=%02x SCALE=%02x ADC=%02x samples=%lu clipped=%lu\r\n",
        reg_read(0x14),reg_read(0x16),reg_read(0x17),
        (unsigned long)mic_samples,(unsigned long)mic_clipped);
    cdc_message(line);
    snprintf(line,sizeof(line),"CUES started=%lu,%lu,%lu completed=%lu,%lu,%lu errors=%lu max_wait_ms=%lu pending=%d\r\n",
        (unsigned long)cue_started[0],(unsigned long)cue_started[1],(unsigned long)cue_started[2],
        (unsigned long)cue_completed[0],(unsigned long)cue_completed[1],(unsigned long)cue_completed[2],
        (unsigned long)cue_errors,(unsigned long)cue_max_wait_ms,cue_pending);
    cdc_message(line);
}
static void local_phrase(int level){
    if(!ready)return;
    cue_started[level-1]++;
    // The higher-priority Wi-Fi writer must yield before reacquiring tx_lock.
    // Otherwise a continuous stream (including silence) can starve this cue.
    cue_pending=true;
    TickType_t waiting_since=xTaskGetTickCount();
    int blocks=dan_cue_samples(level)/240;
    notification_until=xTaskGetTickCount()+pdMS_TO_TICKS(blocks*5+150);
    xSemaphoreTake(tx_lock,portMAX_DELAY);
    uint32_t waited=(xTaskGetTickCount()-waiting_since)*portTICK_PERIOD_MS;
    if(waited>cue_max_wait_ms)cue_max_wait_ms=waited;
    notification_until=xTaskGetTickCount()+pdMS_TO_TICKS(blocks*5+150);
    bool success=true;
    int16_t stereo[480];
    for(int block=0;block<blocks;block++){
        for(int i=0;i<240;i++){
            int16_t v=dan_cue_sample(level,block*240+i);
            stereo[2*i]=stereo[2*i+1]=v;
        }
        size_t written=0;
        esp_err_t result=i2s_channel_write(tx,stereo,sizeof(stereo),&written,100);
        if(result!=ESP_OK||written!=sizeof(stereo)){cue_errors++;success=false;}
    }
    xSemaphoreGive(tx_lock);
    cue_pending=false;
    if(success)cue_completed[level-1]++;
}
void app_main(void) {
    tx_lock=xSemaphoreCreateMutex();
    init_result=audio_init();ready=init_result==ESP_OK;
    uac_device_config_t uc={.output_cb=usb_output_cb,.input_cb=usb_input_cb,.set_mute_cb=mute_cb,.set_volume_cb=volume_cb};
    ESP_ERROR_CHECK(uac_device_init(&uc));
    wifi_audio_init(input_cb,output_cb);
    gpio_config_t button={.pin_bit_mask=1ULL<<41,.mode=GPIO_MODE_INPUT,.pull_up_en=GPIO_PULLUP_ENABLE};
    ESP_ERROR_CHECK(gpio_config(&button));
    int button_raw=1,button_stable=1;TickType_t button_changed=0;
    bool prev_requested=false;
    char command[320];size_t command_len=0;bool receiving_config=false;
    while(1){
        int current=gpio_get_level(41);TickType_t now=xTaskGetTickCount();
        if(current!=button_raw){button_raw=current;button_changed=now;}
        if(current!=button_stable&&now-button_changed>=pdMS_TO_TICKS(35)){
            button_stable=current;
            if(!current)wifi_audio_set_requested(!wifi_audio_requested());
        }
        bool local_cue;
        bool wanted=wifi_audio_requested_with_cue(&local_cue);
        // Acknowledge user intent immediately, once. Network readiness can flap
        // while connecting or recovering; it must never sound like a new call.
        if(wanted!=prev_requested&&local_cue){local_phrase(wanted?1:2);}
        prev_requested=wanted;
        while(tud_cdc_available()){
            char c;tud_cdc_read(&c,1);
            if(receiving_config){
                if(c=='\n'){
                    command[command_len]=0;int result=wifi_audio_configure(command);
                    memset(command,0,sizeof(command));receiving_config=false;command_len=0;
                    char msg[64];snprintf(msg,sizeof(msg),"CONFIG result=%d\r\n",result);cdc_message(msg);
                }else if(command_len<sizeof(command)-1)command[command_len++]=c;
                else {receiving_config=false;command_len=0;cdc_message("CONFIG too long\r\n");}
                continue;
            }
            if(c=='W'){receiving_config=true;command_len=0;continue;}
            if(c=='N'){char msg[256];wifi_audio_status(msg,sizeof(msg));cdc_message(msg);}
            if(c=='Q'){char msg[1600];wifi_audio_scan(msg,sizeof(msg));cdc_message(msg);}
            if(c=='?')diagnostics();
            if(c=='T')wifi_audio_set_requested(!wifi_audio_requested());
            if(c=='z'){usb_bytes=usb_peak=tx_peak=mic_peak=write_errors=0;mic_samples=mic_clipped=0;}
            // Live microphone comparisons; speaker settings are independent.
            if(c=='u'){reg_write(0x14,0x14);diagnostics();} // +12 dB
            if(c=='v'){reg_write(0x14,0x16);diagnostics();} // +18 dB (boot default)
            if(c=='w'){reg_write(0x14,0x18);diagnostics();} // +24 dB
            if(c=='x'){reg_write(0x14,0x10);diagnostics();} // original 0 dB
            if(c=='f'){reg_write(0x32,0xff);diagnostics();}
            if(c=='n'){reg_write(0x32,0xbf);diagnostics();}
            if(c=='i'){reg_write(0x09,0x0c);diagnostics();}
            if(c=='j'){reg_write(0x09,0x00);diagnostics();}
            if(c=='p'){reg_write(0x01,0xb5);diagnostics();}
            if(c=='a'){reg_write(0x01,0xbf);diagnostics();}
            if(c>='1'&&c<='3')local_phrase(c-'0');
            if(c=='b'){
                cdc_message("BOOTLOADER\r\n");vTaskDelay(pdMS_TO_TICKS(100));
                REG_WRITE(RTC_CNTL_OPTION1_REG,RTC_CNTL_FORCE_DOWNLOAD_BOOT);
                esp_rom_software_reset_system();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
