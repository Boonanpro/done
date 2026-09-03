from PIL import Image, ImageDraw, ImageFilter
import os
SRC="scripts/_paina_hero"
OUTP="frontend/public/paina/case-styleup.jpg"

def load_crop(name, crop_h):
    im = Image.open(f"{SRC}/{name}").convert("RGB")
    w,h = im.size
    return im.crop((0,0,w,min(crop_h,h)))

setup = load_crop("su_setup.png", 1240)   # 880x1240
form  = load_crop("su_form.png", 1240)

# canvas 16:10
CW, CH = 1600, 1000
# light pink gradient background
bg = Image.new("RGB",(CW,CH),(0,0,0))
top=(253,232,240); bot=(250,243,247)
for y in range(CH):
    t=y/CH
    r=int(top[0]*(1-t)+bot[0]*t); g=int(top[1]*(1-t)+bot[1]*t); b=int(top[2]*(1-t)+bot[2]*t)
    for x in range(CW):
        pass
# faster gradient via draw line
bg = Image.new("RGB",(CW,CH))
d=ImageDraw.Draw(bg)
for y in range(CH):
    t=y/CH
    c=(int(top[0]*(1-t)+bot[0]*t),int(top[1]*(1-t)+bot[1]*t),int(top[2]*(1-t)+bot[2]*t))
    d.line([(0,y),(CW,y)],fill=c)

def rounded(im, rad):
    im=im.convert("RGBA")
    mask=Image.new("L",im.size,0)
    dr=ImageDraw.Draw(mask)
    dr.rounded_rectangle([0,0,im.size[0],im.size[1]],radius=rad,fill=255)
    im.putalpha(mask)
    return im

# scale screens to target height
TH=840
def fit(im):
    w,h=im.size
    nw=int(w*TH/h)
    return im.resize((nw,TH), Image.LANCZOS)

s_im=rounded(fit(setup),36)
f_im=rounded(fit(form),36)

gap=70
total_w=s_im.size[0]+f_im.size[0]+gap
x0=(CW-total_w)//2
y0=(CH-TH)//2

# shadow
def paste_shadow(base, im, x, y):
    sh=Image.new("RGBA",base.size,(0,0,0,0))
    shadow=Image.new("RGBA",im.size,(0,0,0,0))
    a=im.split()[3].point(lambda p: 90 if p>0 else 0)
    solid=Image.new("RGBA",im.size,(40,20,30,255)); solid.putalpha(a)
    sh.paste(solid,(x+0,y+18),solid)
    sh=sh.filter(ImageFilter.GaussianBlur(22))
    base.alpha_composite(sh)

base=bg.convert("RGBA")
paste_shadow(base,s_im,x0,y0)
paste_shadow(base,f_im,x0+s_im.size[0]+gap,y0)
base.alpha_composite(s_im,(x0,y0))
base.alpha_composite(f_im,(x0+s_im.size[0]+gap,y0))

# small step labels
d2=ImageDraw.Draw(base)
base=base.convert("RGB")
base.save(OUTP,quality=88)
print("saved",OUTP, base.size)
