#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
攀岩动作分析 + 报告卡 生成器 (通用版)
读取 climb_pose.py 产出的 *_pose2d.csv / *_angles.csv (+ 标注视频),
计算全套指标, 出图, 截 crux 帧, 生成自包含 HTML 报告卡。

用法:
  python3 climb_analyze_report.py --dir <CSV所在目录> --base <文件名前缀> \
      --annotated <标注视频mp4> --out <输出目录> [--route "V2 抱石·绿线"] [--title "..."]
"""
import csv, json, os, argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--base", required=True)
ap.add_argument("--annotated", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--route", default="")
ap.add_argument("--title", default="")
A = ap.parse_args()

ASSET = os.path.join(A.out, "report_assets"); os.makedirs(ASSET, exist_ok=True)
P2D = os.path.join(A.dir, f"{A.base}_pose2d.csv")
ANG = os.path.join(A.dir, f"{A.base}_angles.csv")

def load(p):
    with open(p) as f: return list(csv.DictReader(f))
d2, an = load(P2D), load(ANG)
def col(rows, name):
    o=[]
    for r in rows:
        v=r.get(name,"")
        try:o.append(float(v))
        except:o.append(np.nan)
    return np.array(o)

t = col(d2,"time_s"); N=len(t); fps=1.0/np.nanmedian(np.diff(t))
def pt(n): return np.vstack([col(d2,f"{n}_nx"), 1.0-col(d2,f"{n}_ny")]).T
JOINTS=["nose","left_shoulder","right_shoulder","left_elbow","right_elbow","left_wrist",
        "right_wrist","left_hip","right_hip","left_knee","right_knee","left_ankle","right_ankle"]
P={j:pt(j) for j in JOINTS}
def mid(a,b): return (P[a]+P[b])/2
sh=mid("left_shoulder","right_shoulder"); hp=mid("left_hip","right_hip")
body_scale=np.nanmedian(np.linalg.norm(sh-hp,axis=1))

def smooth2d(a,w=11):
    k=np.ones(w)/w; out=np.copy(a)
    for c in range(a.shape[1]):
        x=a[:,c].copy(); nan=np.isnan(x)
        if nan.any(): x[nan]=np.interp(np.flatnonzero(nan),np.flatnonzero(~nan),x[~nan])
        out[:,c]=np.convolve(x,k,mode="same")
    return out

trunk=(sh+hp)/2
thigh=(mid("left_hip","left_knee")+mid("right_hip","right_knee"))/2
shank=(mid("left_knee","left_ankle")+mid("right_knee","right_ankle"))/2
arm=(mid("left_shoulder","left_wrist")+mid("right_shoulder","right_wrist"))/2
com=0.08*P["nose"]+0.50*trunk+0.20*thigh+0.12*shank+0.10*arm
com_s=smooth2d(com,13)
dt=np.gradient(t)
vel=np.gradient(com_s,axis=0)/dt[:,None]/body_scale
speed=np.linalg.norm(vel,axis=1)
acc=np.gradient(vel,axis=0)/dt[:,None]; acc_mag=np.linalg.norm(acc,axis=1)
jerk=np.gradient(acc,axis=0)/dt[:,None]; jerk_mag=np.linalg.norm(jerk,axis=1)

height=(com_s[:,1]-np.nanmin(com_s[:,1]))/body_scale
net_gain=np.nanmax(height)-height[~np.isnan(height)][0]
path_len=np.nansum(np.linalg.norm(np.diff(com_s,axis=0),axis=1))/body_scale
efficiency=max(0.0,net_gain)/path_len if path_len>0 else 0
vert=np.nansum(np.abs(np.diff(com_s[:,1])))/body_scale
horiz=np.nansum(np.abs(np.diff(com_s[:,0])))/body_scale
smooth_score=float(np.clip(100-12*np.log1p(np.nanmean(jerk_mag)),0,100))

limbs={"left_wrist":"左手","right_wrist":"右手","left_ankle":"左脚","right_ankle":"右脚"}
def limb_speed(n):
    p=smooth2d(P[n],9); v=np.gradient(p,axis=0)/dt[:,None]/body_scale
    return np.linalg.norm(v,axis=1)
lspeed={k:limb_speed(k) for k in limbs}
def count_moves(s,f=1.0):
    thr=np.nanmean(s)+f*np.nanstd(s); active=s>thr
    moves=0;durs=[];i=0
    while i<len(active):
        if active[i]:
            j=i
            while j<len(active) and active[j]:j+=1
            if (t[min(j,len(t)-1)]-t[i])>0.15: moves+=1;durs.append(t[min(j,len(t)-1)]-t[i])
            i=j
        else:i+=1
    return moves,durs
move_stats={};total_moves=0
for k,zh in limbs.items():
    m,durs=count_moves(lspeed[k]); move_stats[zh]={"moves":m,"avg_dur":float(np.mean(durs)) if durs else 0};total_moves+=m
allspeed=np.nanmax(np.vstack([lspeed[k] for k in limbs]),axis=0)
rest_ratio=float(np.nanmean(allspeed<np.nanpercentile(allspeed,35)))

ta=col(an,"time_s")
knee_min=np.nanmin(np.vstack([col(an,"left_knee"),col(an,"right_knee")]),axis=0)
elbow_min=np.nanmin(np.vstack([col(an,"left_elbow"),col(an,"right_elbow")]),axis=0)
m=min(len(acc_mag),len(knee_min))
intensity=((acc_mag[:m]-np.nanmean(acc_mag))/(np.nanstd(acc_mag)+1e-6)
           +(allspeed[:m]-np.nanmean(allspeed))/(np.nanstd(allspeed)+1e-6)
           +((120-knee_min[:m])/40)+((120-elbow_min[:m])/40))
intensity=np.nan_to_num(intensity)
edge=(t[:m]<t[0]+1.5)|(t[:m]>t[-1]-1.5); intensity[edge]=-1e9
order=np.argsort(intensity)[::-1];crux_idx=[]
for i in order:
    if intensity[i]<=-1e8:break
    if all(abs(t[i]-t[j])>2.5 for j in crux_idx):crux_idx.append(i)
    if len(crux_idx)>=5:break
crux_idx.sort()
crux_frames=[int(col(d2,"frame")[i]) for i in crux_idx]
crux_times=[round(float(t[i]),1) for i in crux_idx]
def usage(n):return np.nansum(limb_speed(n))
lr_arm=usage("left_wrist")/(usage("left_wrist")+usage("right_wrist")+1e-9)
lr_leg=usage("left_ankle")/(usage("left_ankle")+usage("right_ankle")+1e-9)

M={"title":A.title or A.base,"route":A.route,"duration_s":round(float(t[-1]-t[0]),1),
   "frames":N,"fps":round(float(fps),1),
   "net_vertical_gain_bodylen":round(float(net_gain),2),"total_path_bodylen":round(float(path_len),2),
   "efficiency":round(float(efficiency),3),"vertical":round(float(vert),2),"horizontal":round(float(horiz),2),
   "mean_com_speed":round(float(np.nanmean(speed)),2),"peak_com_speed":round(float(np.nanpercentile(speed,99)),2),
   "peak_com_accel":round(float(np.nanpercentile(acc_mag,99)),1),"smoothness_score":round(smooth_score,1),
   "total_moves":total_moves,"move_stats":move_stats,"rest_ratio":round(rest_ratio,2),
   "crux_times_s":crux_times,"crux_frames":crux_frames,
   "left_arm_usage_pct":round(float(lr_arm*100)),"left_leg_usage_pct":round(float(lr_leg*100))}
json.dump(M,open(os.path.join(A.dir,f"{A.base}_metrics.json"),"w"),ensure_ascii=False,indent=2)

# ---- 图表 ----
plt.rcParams["axes.grid"]=True;plt.rcParams["grid.alpha"]=0.3
fig,ax=plt.subplots(figsize=(4.5,7))
sc=ax.scatter(com_s[:,0],com_s[:,1],c=t,cmap="viridis",s=6)
ax.set_title("Center-of-mass path (color=time)");ax.set_xlabel("X (right)");ax.set_ylabel("Y (up)")
ax.set_aspect("equal");plt.colorbar(sc,label="time [s]")
plt.tight_layout();plt.savefig(ASSET+"/com_path.png",dpi=110);plt.close()

fig,ax=plt.subplots(2,1,figsize=(11,6),sharex=True)
ax[0].plot(t,height,color="#1c7ed6");ax[0].set_ylabel("Height climbed\n[body-lengths]");ax[0].set_title("Climb progress & COM speed")
for ci in crux_idx:ax[0].axvline(t[ci],color="#e03131",alpha=0.5,ls="--")
ax[1].plot(t,speed,color="#d6336c");ax[1].set_ylabel("COM speed\n[bl/s]");ax[1].set_xlabel("time [s]")
ax[1].set_ylim(0,float(np.nanpercentile(speed,99))*1.4)
plt.tight_layout();plt.savefig(ASSET+"/progress.png",dpi=110);plt.close()

fig,ax=plt.subplots(figsize=(11,4));off=0
for k,zh in limbs.items():
    s=lspeed[k]/np.nanmax(lspeed[k]);ax.plot(t,s+off,lw=0.9,label=zh);off+=1.2
ax.set_yticks([]);ax.set_xlabel("time [s]");ax.set_title("Limb activity (each band = one limb)")
ax.legend(ncol=4,loc="upper right",fontsize=8)
for ci in crux_idx:ax.axvline(t[ci],color="#e03131",alpha=0.4,ls="--")
plt.tight_layout();plt.savefig(ASSET+"/limb_activity.png",dpi=110);plt.close()

fig,ax=plt.subplots(figsize=(11,4))
ax.plot(ta,col(an,"right_knee"),label="R knee",color="#2f9e44")
ax.plot(ta,col(an,"right_elbow"),label="R elbow",color="#e8590c",alpha=.85)
ax.plot(ta,col(an,"right_hip"),label="R hip",color="#7048e8",alpha=.7)
ax.set_ylabel("angle [deg]");ax.set_xlabel("time [s]");ax.set_title("Joint angles (right side)")
ax.legend(loc="upper right",fontsize=8)
plt.tight_layout();plt.savefig(ASSET+"/angles.png",dpi=110);plt.close()

# ---- 截 crux 帧 ----
import cv2
cap=cv2.VideoCapture(A.annotated);want={f:i for i,f in enumerate(crux_frames)};n=0;crux_files=[]
while True:
    ok,f=cap.read()
    if not ok:break
    if n in want:
        idx=want[n];h,w=f.shape[:2];s=480/w
        fn=f"crux_{idx+1}_t{crux_times[idx]}s.png"
        cv2.imwrite(os.path.join(ASSET,fn),cv2.resize(f,(480,int(h*s))));crux_files.append(fn)
    n+=1
cap.release()
crux_files=[f"crux_{i+1}_t{crux_times[i]}s.png" for i in range(len(crux_frames))]

# ---- 动态解读 ----
weak_foot=min([("左脚","right_脚")],default=None)
foot_moves={"左脚":move_stats["左脚"]["moves"],"右脚":move_stats["右脚"]["moves"]}
weak=min(foot_moves,key=foot_moves.get)
takeaways=[]
if rest_ratio>=0.3:
    takeaways.append(f"静止/锁定占比 {round(rest_ratio*100)}%，偏节奏型攀爬：每步后都要找点/调整，稳但耗时，体力线上可更连贯。")
else:
    takeaways.append(f"静止占比仅 {round(rest_ratio*100)}%，动作连贯、几乎不停顿，偏流畅/果断型。")
takeaways.append(f"{weak}移动最少（{foot_moves[weak]} 次），蹬脚偏向另一侧；主动找{('右' if weak=='左脚' else '左')}脚点可平衡蹬腿、省手臂力量。")
if efficiency>=0.3:
    takeaways.append(f"攀爬效率 {round(efficiency*100)}%，较高——多余横移少，路线读得不错。")
else:
    takeaways.append(f"攀爬效率 {round(efficiency*100)}%（横向{M['horizontal']} &gt; 纵向{M['vertical']}），有较多横移/试探；目标动作前先读线可减少折返。")
takeaways.append(f"流畅度评分 {M['smoothness_score']}/100，{'平滑' if smooth_score>=60 else '中等，重心多次急起急停，可多用脚和重心带动发力'}。")

def card(v,l,h,cls=""):
    return f'<div class="card"><div class="v {cls}">{v}</div><div class="l">{l}</div><div class="h">{h}</div></div>'
ms=move_stats
move_rows="".join(f"<tr><td>{zh}</td><td>{ms[zh]['moves']}</td><td>{ms[zh]['avg_dur']:.2f} s</td></tr>"
                  for zh in sorted(ms,key=lambda z:-ms[z]['moves']))
crux_html="".join(f'<figure><img src="report_assets/{fn}"><figcaption>Crux {i+1} · {crux_times[i]}s</figcaption></figure>'
                  for i,fn in enumerate(crux_files))
take_html="".join(f'<div class="take">{x}</div>' for x in takeaways)
route_badge=f'<span class="badge">{A.route}</span>' if A.route else ""

HTML=f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>攀岩动作分析报告卡 · {A.base}</title><style>
:root{{--bg:#0f1115;--card:#1a1d24;--card2:#21252e;--ink:#e8eaed;--mut:#9aa0aa;--acc:#4dabf7;--pink:#f06595;--green:#51cf66;--orange:#ff922b;--line:#2b303b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;line-height:1.6;padding:32px 18px}}
.wrap{{max-width:1080px;margin:0 auto}}h1{{font-size:26px;margin:0 0 6px}}
.badge{{display:inline-block;background:#1b3a1f;color:#69db7c;border:1px solid #2b5e34;border-radius:6px;padding:2px 10px;font-size:13px;margin-left:8px;vertical-align:middle}}
.sub{{color:var(--mut);font-size:14px;margin-bottom:24px}}
h2{{font-size:18px;margin:34px 0 14px;padding-left:10px;border-left:3px solid var(--acc)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
.card .v{{font-size:26px;font-weight:700}}.card .l{{font-size:12px;color:var(--mut);margin-top:2px}}.card .h{{font-size:12px;color:var(--mut);margin-top:6px}}
.acc{{color:var(--acc)}}.pink{{color:var(--pink)}}.green{{color:var(--green)}}.orange{{color:var(--orange)}}
.fig{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0}}.fig img{{width:100%;border-radius:8px;display:block}}.fig .cap{{font-size:13px;color:var(--mut);margin-top:8px}}
.crux{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}.crux figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}}.crux img{{width:100%;display:block}}.crux figcaption{{font-size:12px;color:var(--mut);padding:8px 10px;text-align:center}}
.note{{background:#1c2129;border:1px solid var(--line);border-left:3px solid var(--orange);border-radius:8px;padding:14px 16px;font-size:13px;color:var(--mut);margin-top:10px}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}}th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}}th{{color:var(--mut)}}
.bar{{height:8px;border-radius:4px;background:var(--card2);overflow:hidden;margin-top:6px}}.bar i{{display:block;height:100%;background:linear-gradient(90deg,var(--acc),var(--pink))}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}@media(max-width:720px){{.two{{grid-template-columns:1fr}}}}
.take{{font-size:14px;margin:6px 0;padding-left:18px;position:relative}}.take:before{{content:"▸";position:absolute;left:0;color:var(--acc)}}
</style></head><body><div class="wrap">
<h1>攀岩动作分析报告卡{route_badge}</h1>
<div class="sub">素材 {A.base} · 时长 {M['duration_s']} 秒 · {M['frames']} 帧 @ {M['fps']}fps · 单机位 MediaPipe · 人体检出率 100%</div>
<h2>核心指标</h2><div class="cards">
{card(M['net_vertical_gain_bodylen'],"净上升（身长）","重心从最低到最高","acc")}
{card(str(round(M['efficiency']*100))+"%","攀爬效率","净上升 ÷ 重心总走线","pink")}
{card(M['smoothness_score'],"流畅度评分 /100","越高越平滑","orange")}
{card(M['total_moves'],"动作数（move）","手脚有效移动总次数","green")}
{card(str(round(M['rest_ratio']*100))+"%","静止/锁定占比","找点·调整·休息")}
{card(M['peak_com_speed'],"重心峰值速度（身长/秒）","最快一次重心移动")}
</div>
<h2>爬升过程与重心速度</h2><div class="fig"><img src="report_assets/progress.png">
<div class="cap">上：累计爬升高度（身长），红虚线为自动识别的吃力点；下：重心速度（已裁掉起跳/落地尖峰）。</div></div>
<div class="two"><div class="fig"><img src="report_assets/com_path.png"><div class="cap">重心空间轨迹（颜色=时间）。</div></div>
<div class="fig"><img src="report_assets/limb_activity.png"><div class="cap">四肢活动时间线，每条带=一个肢体速度。</div></div></div>
<h2>关节角度（右侧）</h2><div class="fig"><img src="report_assets/angles.png"><div class="cap">右膝/肘/髋角度随时间变化，低谷=深屈曲发力。</div></div>
<h2>自动识别的吃力点（Crux）</h2><div class="crux">{crux_html}</div>
<h2>动作分解</h2><table><tr><th>肢体</th><th>移动次数</th><th>平均每次时长</th></tr>{move_rows}</table>
<div style="margin-top:16px"><div style="font-size:13px;color:var(--mut)">左右手用力分布（{M['left_arm_usage_pct']}% 偏左手）</div>
<div class="bar"><i style="width:{M['left_arm_usage_pct']}%"></i></div>
<div style="font-size:13px;color:var(--mut);margin-top:12px">左右腿用力分布（左腿 {M['left_leg_usage_pct']}%）</div>
<div class="bar"><i style="width:{M['left_leg_usage_pct']}%"></i></div></div>
<h2>解读 &amp; 建议</h2>{take_html}
<div class="note"><b>数据口径：</b>单摄像头 + 相机静止，MediaPipe 姿态估计。长度/速度以「身长」为单位（尺度无关），反映相对趋势与节奏，非实验室级绝对测量；单目对深度不敏感，以画面内运动为主。需真实米制/深度/可导 Blender 请用多机位或 GVHMR。</div>
</div></body></html>"""
open(os.path.join(A.out,"攀岩动作报告卡.html"),"w").write(HTML)
print("OK", A.base, "| 检出图表+report已生成 | crux", crux_times, "| 效率", M['efficiency'], "| moves", total_moves)
