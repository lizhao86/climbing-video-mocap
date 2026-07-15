#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""攀岩动作全套指标分析。读取 pose2d/angles CSV, 输出图表 + 指标 JSON。
单目 + 相机静止假设。所有速度以"身长/秒"为单位(尺度无关, 适合单目)。"""
import csv, json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

D = "/sessions/loving-hopeful-babbage/mnt/climbing-video-动捕/"
ASSET = D + "report_assets/"
os.makedirs(ASSET, exist_ok=True)
P2D = D + "IMG_6424_pose2d.csv"
ANG = D + "IMG_6424_angles.csv"

# ---------- 读数据 ----------
def load(p):
    with open(p) as f:
        return list(csv.DictReader(f))

d2 = load(P2D)
an = load(ANG)

def col(rows, name):
    out = []
    for r in rows:
        v = r.get(name, "")
        try: out.append(float(v))
        except: out.append(np.nan)
    return np.array(out)

t = col(d2, "time_s")
N = len(t)
fps = 1.0 / np.nanmedian(np.diff(t))

# 取归一化 2D, 转成"上为正"的坐标系: X 右正, Y 上正
def pt(name):
    x = col(d2, f"{name}_nx")
    y = 1.0 - col(d2, f"{name}_ny")   # 翻转: 越往上越大
    return np.vstack([x, y]).T

JOINTS = ["nose","left_shoulder","right_shoulder","left_elbow","right_elbow",
          "left_wrist","right_wrist","left_hip","right_hip","left_knee","right_knee",
          "left_ankle","right_ankle"]
P = {j: pt(j) for j in JOINTS}

def mid(a, b): return (P[a] + P[b]) / 2

# ---------- 身体尺度(身长) ----------
sh = mid("left_shoulder","right_shoulder")
hp = mid("left_hip","right_hip")
torso_len = np.linalg.norm(sh - hp, axis=1)
body_scale = np.nanmedian(torso_len)          # 1 身长 ~ 这么多归一化单位 (躯干长)
print(f"帧数 {N}, fps {fps:.1f}, 躯干尺度 {body_scale:.4f}")

# ---------- 重心 COM (分段质量加权) ----------
# 简化 de Leva: 躯干0.50 头0.08 双大腿0.20 双小腿+足0.12 双上臂+前臂+手0.10
def seg(*names):
    return np.nanmean([P[n] for n in names], axis=0)
com = (0.08*P["nose"] + 0.50*mid_trunk if False else None)  # placeholder
trunk = (sh + hp) / 2
thigh = (mid("left_hip","left_knee") + mid("right_hip","right_knee")) / 2
shank = (mid("left_knee","left_ankle") + mid("right_knee","right_ankle")) / 2
arm   = (mid("left_shoulder","left_wrist") + mid("right_shoulder","right_wrist")) / 2
com = 0.08*P["nose"] + 0.50*trunk + 0.20*thigh + 0.12*shank + 0.10*arm

def smooth2d(a, w=11):
    k = np.ones(w)/w
    out = np.copy(a)
    for c in range(a.shape[1]):
        x = a[:, c]
        nan = np.isnan(x)
        if nan.any():
            x = x.copy(); x[nan] = np.interp(np.flatnonzero(nan), np.flatnonzero(~nan), x[~nan])
        out[:, c] = np.convolve(x, k, mode="same")
    return out

com_s = smooth2d(com, 13)

# ---------- 速度/加速度/jerk (身长单位) ----------
dt = np.gradient(t)
vel = np.gradient(com_s, axis=0) / dt[:, None] / body_scale     # 身长/s
speed = np.linalg.norm(vel, axis=1)
acc = np.gradient(vel, axis=0) / dt[:, None]                    # 身长/s^2
acc_mag = np.linalg.norm(acc, axis=1)
jerk = np.gradient(acc, axis=0) / dt[:, None]
jerk_mag = np.linalg.norm(jerk, axis=1)

# ---------- 爬升进展 & 效率 ----------
height = (com_s[:,1] - np.nanmin(com_s[:,1])) / body_scale       # 相对最低点的高度(身长)
net_gain = np.nanmax(height) - height[~np.isnan(height)][0]
path_len = np.nansum(np.linalg.norm(np.diff(com_s, axis=0), axis=1)) / body_scale
efficiency = max(0.0, net_gain) / path_len if path_len > 0 else 0   # 净上升 / 总走线
# 横向折腾占比
horiz = np.nansum(np.abs(np.diff(com_s[:,0]))) / body_scale
vert  = np.nansum(np.abs(np.diff(com_s[:,1]))) / body_scale

# ---------- 流畅度评分 (基于无量纲 jerk) ----------
T = t[-1] - t[0]
mean_v = np.nanmean(speed) + 1e-6
dimensionless_jerk = np.nanmean(jerk_mag**2) * (T**5) / (np.nanmax(height)+1e-6)**2
# 映射成 0~100: jerk 越小越顺. 用对数压缩 + 经验缩放
sm_raw = np.nanmean(jerk_mag)
smooth_score = float(np.clip(100 - 12*np.log1p(sm_raw), 0, 100))

# ---------- 动作分段: 手脚移动 vs 静止 ----------
def limb_speed(name):
    p = smooth2d(P[name], 9)
    v = np.gradient(p, axis=0)/dt[:,None]/body_scale
    return np.linalg.norm(v, axis=1)
limbs = {"left_wrist":"左手","right_wrist":"右手","left_ankle":"左脚","right_ankle":"右脚"}
lspeed = {k: limb_speed(k) for k in limbs}

def count_moves(s, thr_factor=1.0):
    thr = np.nanmean(s) + thr_factor*np.nanstd(s)
    active = s > thr
    # 计连续活跃段
    moves = 0; durs = []; i = 0
    while i < len(active):
        if active[i]:
            j = i
            while j < len(active) and active[j]: j += 1
            if (t[min(j,len(t)-1)] - t[i]) > 0.15:   # 至少0.15s才算一次move
                moves += 1; durs.append(t[min(j,len(t)-1)]-t[i])
            i = j
        else:
            i += 1
    return moves, durs

move_stats = {}
total_moves = 0
for k,zh in limbs.items():
    m, durs = count_moves(lspeed[k], 1.0)
    move_stats[zh] = {"moves": m, "avg_dur": float(np.mean(durs)) if durs else 0}
    total_moves += m

# 整体静止(休息/锁定)比例: 所有肢体都低速
allspeed = np.nanmax(np.vstack([lspeed[k] for k in limbs]), axis=0)
rest_thr = np.nanpercentile(allspeed, 35)
rest_ratio = float(np.nanmean(allspeed < rest_thr))

# ---------- crux 定位 ----------
# 综合强度 = COM加速度 + 最大肢体速度 + 关节极端度
ta = col(an, "time_s")
def angcol(n): return col(an, n)
knee_min = np.nanmin(np.vstack([angcol("left_knee"), angcol("right_knee")]), axis=0)
elbow_min = np.nanmin(np.vstack([angcol("left_elbow"), angcol("right_elbow")]), axis=0)
# 对齐长度
m = min(len(acc_mag), len(knee_min))
intensity = ( (acc_mag[:m]-np.nanmean(acc_mag))/ (np.nanstd(acc_mag)+1e-6)
            + (allspeed[:m]-np.nanmean(allspeed))/(np.nanstd(allspeed)+1e-6)
            + ((120-knee_min[:m])/40) + ((120-elbow_min[:m])/40) )
intensity = np.nan_to_num(intensity)
# 排除首尾1.5s的差分边界假峰
edge = (t[:m] < t[0]+1.5) | (t[:m] > t[-1]-1.5)
intensity[edge] = -1e9
# 取相互间隔>2.5s的前5个峰
order = np.argsort(intensity)[::-1]
crux_idx = []
for i in order:
    if intensity[i] <= -1e8: break
    if all(abs(t[i]-t[j])>2.5 for j in crux_idx):
        crux_idx.append(i)
    if len(crux_idx) >= 5: break
crux_idx.sort()
crux_times = [round(float(t[i]),2) for i in crux_idx]

# ---------- 左右对称 ----------
def usage(name): return np.nansum(limb_speed(name))
lr_arm = usage("left_wrist")/(usage("left_wrist")+usage("right_wrist")+1e-9)
lr_leg = usage("left_ankle")/(usage("left_ankle")+usage("right_ankle")+1e-9)

metrics = {
    "duration_s": round(float(T),1),
    "frames": N, "fps": round(float(fps),1),
    "net_vertical_gain_bodylen": round(float(net_gain),2),
    "total_path_bodylen": round(float(path_len),2),
    "efficiency": round(float(efficiency),3),
    "vertical_vs_horizontal": [round(float(vert),2), round(float(horiz),2)],
    "mean_com_speed_bl_s": round(float(np.nanmean(speed)),2),
    "peak_com_speed_bl_s": round(float(np.nanpercentile(speed,99)),2),
    "peak_com_accel_bl_s2": round(float(np.nanpercentile(acc_mag,99)),1),
    "smoothness_score": round(smooth_score,1),
    "total_moves": total_moves,
    "move_stats": move_stats,
    "rest_ratio": round(rest_ratio,2),
    "crux_times_s": crux_times,
    "left_arm_usage_pct": round(float(lr_arm*100),0),
    "left_leg_usage_pct": round(float(lr_leg*100),0),
}
json.dump(metrics, open(D+"IMG_6424_metrics.json","w"), ensure_ascii=False, indent=2)
print(json.dumps(metrics, ensure_ascii=False, indent=2))

# ---------- 图表 ----------
plt.rcParams["axes.grid"]=True; plt.rcParams["grid.alpha"]=0.3

# 图1: 重心轨迹 (空间)
fig,axx=plt.subplots(figsize=(4.5,7))
sc=axx.scatter(com_s[:,0], com_s[:,1], c=t, cmap="viridis", s=6)
axx.set_title("Center-of-mass path (color=time)"); axx.set_xlabel("X (right)"); axx.set_ylabel("Y (up)")
axx.set_aspect("equal"); plt.colorbar(sc,label="time [s]")
plt.tight_layout(); plt.savefig(ASSET+"com_path.png",dpi=110); plt.close()

# 图2: 爬升进展 + 速度
fig,ax=plt.subplots(2,1,figsize=(11,6),sharex=True)
ax[0].plot(t,height,color="#1c7ed6"); ax[0].set_ylabel("Height climbed\n[body-lengths]"); ax[0].set_title("Climb progress & COM speed")
for ci in crux_idx: ax[0].axvline(t[ci],color="#e03131",alpha=0.5,ls="--")
ax[1].plot(t,speed,color="#d6336c"); ax[1].set_ylabel("COM speed\n[bl/s]"); ax[1].set_xlabel("time [s]")
ax[1].set_ylim(0, float(np.nanpercentile(speed,99))*1.4)   # 裁掉起跳/落地尖峰, 看清攀爬段
plt.tight_layout(); plt.savefig(ASSET+"progress.png",dpi=110); plt.close()

# 图3: 肢体活动时间线
fig,ax=plt.subplots(figsize=(11,4))
off=0
for k,zh in limbs.items():
    s=lspeed[k]; s=s/np.nanmax(s)
    ax.plot(t, s+off, lw=0.9, label=zh)
    off+=1.2
ax.set_yticks([]); ax.set_xlabel("time [s]"); ax.set_title("Limb activity (each band = one limb's speed)")
ax.legend(ncol=4, loc="upper right", fontsize=8)
for ci in crux_idx: ax.axvline(t[ci],color="#e03131",alpha=0.4,ls="--")
plt.tight_layout(); plt.savefig(ASSET+"limb_activity.png",dpi=110); plt.close()

# 图4: 关节角度
fig,ax=plt.subplots(figsize=(11,4))
ax.plot(ta,angcol("right_knee"),label="R knee",color="#2f9e44")
ax.plot(ta,angcol("right_elbow"),label="R elbow",color="#e8590c",alpha=.85)
ax.plot(ta,angcol("right_hip"),label="R hip",color="#7048e8",alpha=.7)
ax.set_ylabel("angle [deg]"); ax.set_xlabel("time [s]"); ax.set_title("Joint angles (right side)")
ax.legend(loc="upper right",fontsize=8)
plt.tight_layout(); plt.savefig(ASSET+"angles.png",dpi=110); plt.close()

print("\n图表已存到 report_assets/, crux 帧索引:", crux_idx)
print("CRUX_FRAMES:" + ",".join(str(int(col(d2,'frame')[i])) for i in crux_idx))
