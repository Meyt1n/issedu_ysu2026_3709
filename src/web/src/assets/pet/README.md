# 小芽精灵逐帧资源

运行时优先读取 `manifest.ts` 中登记的透明 PNG/WebP 帧；没有登记素材时，
`CompanionPet.vue` 使用同一角色规范的 SVG 离散帧兜底。

推荐目录：

```text
pet/
  idle/frame_01.webp ... frame_06.webp
  blink/frame_01.webp ... frame_04.webp
  wave/frame_01.webp ... frame_06.webp
  happy/frame_01.webp ... frame_04.webp
  cheer/frame_01.webp ... frame_06.webp
  think/frame_01.webp ... frame_06.webp
  shy/frame_01.webp ... frame_04.webp
  sleep/frame_01.webp ... frame_06.webp
  loading/frame_01.webp ... frame_06.webp
  point/frame_01.webp ... frame_06.webp
  listening/frame_01.webp ... frame_06.webp
  reminder/frame_01.webp ... frame_06.webp
  success/frame_01.webp ... frame_06.webp
```

每帧建议使用 `384 × 416` 透明画布、统一脚底基线和身体包围盒；禁止把气泡、
文字、落地阴影或页面背景烘焙进角色帧。文件名一律两位序号，从 `frame_01` 开始。
