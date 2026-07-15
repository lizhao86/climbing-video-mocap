# CHANGELOG

本项目的阶段同步记录。由 evyd-neat-freak skill 维护，每次 /neat 追加一行并刷新总纲。

**总纲：1 次迭代 · ~$28.57 (est.) · 9 files (+4055 −2) · 2026-07-15**

## 明细

| 时间 | 改了什么 | 我的 Prompt | 费用 | 代码量 | Remarks |
|------|----------|-------------|------|--------|---------|
| 2026-07-15 22:31 | S1 知识库构建：精读教材产出 moves.json（54 动作）+ kb_lint.py；补 kb_render.py 生成可浏览 viewer；补 kb_extract_pages.py 嵌入教材页图；实测否决「卡通图跑骨架建 pattern」方案 | "按项目 todo，先做第一个事情？看看计划"<br>"这个 json 对我阅读不够友好，html 格式是不是更好？"<br>"优化，需要增加 pdf 里面的截图，另外要不要在图片上贴上人体骨骼模型的线条，进一步建立 pattern？" | ~$28.57 (est.) / 5h 31m | 9 files (+4055 −2) | 抓到页码偏移 bug：PDF页=印刷页+2 非+1（实测校验）；MediaPipe 卡通图检出 2/7 且关节错位，pattern 只走真实视频标注回流；成本估算按 Opus 价（sonnet-5/fable-5 无价目） |
