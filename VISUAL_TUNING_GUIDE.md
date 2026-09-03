# 视觉调试指南

## 🎨 快速调整图片显示效果

如果某张背景图的占位不对，有两种方法可以调整：

---

## 方法一：浏览器开发者工具实时调试（推荐）

### 1. 打开开发者工具

```
Chrome/Edge: F12 或 右键 → 检查
Firefox: F12 或 右键 → 检查元素
```

### 2. 找到对应的图片元素

#### 首页卡片背景
```css
/* 在 Elements/Inspector 面板中找到 */
.overview-section-art
```

#### 健康新闻卡片背景
```css
.health-news-art
```

### 3. 在 Styles 面板中实时调整

#### 调整图片位置
```css
/* 当前值 */
object-position: center;

/* 可选值 */
object-position: center top;     /* 居中靠上 */
object-position: center bottom;  /* 居中靠下 */
object-position: left center;    /* 靠左居中 */
object-position: right center;   /* 靠右居中 */
object-position: 30% 50%;        /* 自定义百分比 */
```

#### 调整图片不透明度
```css
/* 当前值 */
opacity: 0.45;

/* 建议范围 */
opacity: 0.3;   /* 更淡，更像氛围背景 */
opacity: 0.5;   /* 适中 */
opacity: 0.65;  /* 更明显 */
```

#### 调整图片滤镜
```css
/* 当前值 */
filter: brightness(1.15) saturate(0.98) contrast(0.94);

/* 图片太暗 */
filter: brightness(1.25) saturate(0.98) contrast(0.94);

/* 图片太亮 */
filter: brightness(1.05) saturate(0.98) contrast(0.94);

/* 图片太灰 */
filter: brightness(1.15) saturate(1.1) contrast(0.94);

/* 图片对比度太强 */
filter: brightness(1.15) saturate(0.98) contrast(0.85);
```

### 4. 调整遮罩强度

如果文字不够清晰，调整遮罩：

#### 首页卡片遮罩
```css
.overview-section-wash {
  background: linear-gradient(
    115deg,
    rgba(255, 252, 243, 0.96) 0%,    /* 增大这个值让左侧更不透明 */
    rgba(255, 252, 243, 0.92) 35%,
    rgba(255, 252, 243, 0.84) 65%,
    rgba(255, 252, 243, 0.72) 100%
  );
}
```

#### 健康新闻遮罩
```css
.health-news-wash {
  background: linear-gradient(
    100deg,
    rgba(255, 252, 244, 0.96) 0%,    /* 增大这个值让左侧更不透明 */
    rgba(255, 252, 244, 0.88) 28%,
    rgba(255, 252, 244, 0.6) 58%,
    rgba(255, 252, 244, 0.2) 85%,
    rgba(255, 252, 244, 0) 100%
  );
}
```

---

## 方法二：修改代码固化调整

找到满意的参数后，将它们写入代码：

### 1. 首页卡片 - 修改 OverviewView.vue

找到对应卡片的样式：

```css
/* 例如调整"待确认事项"的图片位置 */
.overview-section--pending .overview-section-art {
  object-position: center top;  /* 改为靠上显示 */
  opacity: 0.4;                 /* 降低不透明度 */
}
```

### 2. 健康新闻 - 修改 HealthNewsPanel.vue

```css
.health-news-art {
  object-position: left center;  /* 改为靠左显示 */
  filter: brightness(1.2) saturate(1.05) contrast(0.98);
}
```

---

## 常见问题和解决方案

### 问题 1: 图片主体被文字遮挡

**症状**: 图片的重要内容（比如桌面上的笔记本）被卡片文字盖住了

**解决方案**:
```css
/* 将图片向右移动 */
object-position: right center;

/* 或者向左移动 */
object-position: left center;

/* 或者向上/下移动 */
object-position: center top;
object-position: center bottom;
```

### 问题 2: 图片太亮/太暗

**症状**: 图片显示效果不理想

**解决方案**:
```css
/* 图片太亮 - 降低亮度 */
filter: brightness(1.0) saturate(0.98) contrast(0.94);

/* 图片太暗 - 提高亮度 */
filter: brightness(1.3) saturate(0.98) contrast(0.94);
```

### 问题 3: 图片颜色太鲜艳

**症状**: 图片颜色过于饱和，不够自然

**解决方案**:
```css
/* 降低饱和度 */
filter: brightness(1.15) saturate(0.85) contrast(0.94);
```

### 问题 4: 文字看不清

**症状**: 卡片上的文字不够清晰

**解决方案 A - 降低图片不透明度**:
```css
.overview-section-art {
  opacity: 0.35;  /* 从 0.45 降到 0.35 */
}
```

**解决方案 B - 加强遮罩**:
```css
.overview-section-wash {
  background: linear-gradient(
    115deg,
    rgba(255, 252, 243, 0.98) 0%,    /* 从 0.96 提高到 0.98 */
    rgba(255, 252, 243, 0.94) 35%,   /* 从 0.92 提高到 0.94 */
    /* ... */
  );
}
```

### 问题 5: 图片显示范围不对

**症状**: 图片被裁剪掉重要部分

**解决方案**:
```css
/* 改变裁剪方式（不推荐，可能出现白边） */
object-fit: contain;  /* 完整显示，可能有白边 */

/* 保持 cover，调整位置 */
object-fit: cover;
object-position: 40% 50%;  /* 精确控制显示区域 */
```

---

## 推荐的调试流程

1. **打开页面** - 访问 http://localhost:5173
2. **找到问题卡片** - 定位显示不正常的卡片
3. **打开开发者工具** - F12
4. **选择元素** - 点击左上角的选择工具，点击问题卡片
5. **找到图片元素** - 在 DOM 树中找到 `.overview-section-art` 或 `.health-news-art`
6. **实时调整** - 在 Styles 面板中修改 CSS 属性
7. **记录参数** - 找到满意的参数后记录下来
8. **修改代码** - 将参数写入对应的 .vue 文件
9. **验证效果** - 刷新页面确认效果

---

## 各卡片的当前配置

### 首页概览卡片

| 卡片名称 | 图片文件 | object-position | opacity | 说明 |
|---------|---------|----------------|---------|------|
| 待确认事项 | pending-tasks.jpg | center | 0.45 | 桌面待办场景 |
| 今日用药 | medication-schedule.jpg | center | 0.45 | 药盒和日历 |
| 最近识别 | recent-scans.jpg | center | 0.45 | 药盒特写 |
| 家庭成员 | family-members.jpg | center | 0.45 | 家庭角落 |
| 近期变化 | recent-changes.jpg | center | 0.45 | 健康日志 |

### 健康新闻卡片

| 配置项 | 当前值 | 说明 |
|--------|--------|------|
| object-position | center right | 图片靠右显示，左侧留出文字空间 |
| opacity | 1 | 完全不透明 |
| filter | brightness(1.08) saturate(1.02) | 轻微提亮 |
| 文字区域宽度 | 65% | 左侧 65% 用于文字 |

---

## 快捷调整代码片段

### 让所有首页卡片图片更淡
```css
/* 在 OverviewView.vue 的 .overview-section-art 中 */
opacity: 0.35;  /* 从 0.45 改为 0.35 */
```

### 让健康新闻图片更靠右
```css
/* 在 HealthNewsPanel.vue 的 .health-news-art 中 */
object-position: right center;  /* 从 center right 改为 right center */
```

### 让某个特定卡片的图片居中靠上
```css
/* 在 OverviewView.vue 中添加 */
.overview-section--pending .overview-section-art {
  object-position: center top;
}
```

---

## 工具推荐

### 在线 CSS 调试
- **Chrome DevTools** - 最推荐，实时预览
- **Firefox Developer Tools** - 同样好用

### 图片编辑（如果需要修改源图片）
- **Photoshop** - 调整亮度、对比度、裁剪
- **GIMP** - 免费替代品
- **在线工具**:
  - Photopea (photopea.com) - 在线 PS
  - Remove.bg (remove.bg) - 去背景
  - TinyJPG (tinyjpg.com) - 压缩

---

## 最佳实践

### 1. 图片不透明度建议
- **氛围背景**: 0.3 - 0.4
- **平衡显示**: 0.45 - 0.55
- **突出图片**: 0.6 - 0.8

### 2. 遮罩强度建议
- **文字为主**: 遮罩不透明度 0.95 - 0.98
- **平衡显示**: 遮罩不透明度 0.85 - 0.92
- **图片为主**: 遮罩不透明度 0.7 - 0.8

### 3. 图片位置建议
- **有明确主体**: 使用 object-position 让主体不被遮挡
- **均匀场景**: center 居中显示
- **左右布局**: 文字在左用 right center，文字在右用 left center

---

## 如果还是不满意

### 选项 1: 调整图片本身
用图片编辑软件调整源图片：
1. 提高亮度 +10-20%
2. 降低饱和度 -5-10%
3. 增加暖色调
4. 裁剪构图

### 选项 2: 更换图片
重新生成或下载更合适的图片：
1. 查看 `IMAGE_GENERATION_PROMPTS.md`
2. 调整提示词
3. 重新生成
4. 替换文件

### 选项 3: 调整布局
如果图片实在不适合当前布局：
1. 调整文字区域宽度
2. 改变卡片高度
3. 调整内边距

---

**记住**: 最好的调试方式是在浏览器开发者工具中实时调整，找到满意的参数后再写入代码！
