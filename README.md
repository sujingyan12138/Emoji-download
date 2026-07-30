# 表情中转站 Emoji Bridge

## 这个项目有什么用

这是一个面向 Windows 的本地表情整理项目，用来把 QQ 和抖音中的表情原件
保存到本地，方便备份、整理和跨平台使用。

项目包含两个部分：

- **QQ 桌面工具**：自动查找 QQ NT 的“喜欢”表情，识别图片真实格式，
  预览静态或动态内容，并把原文件复制到项目的 `library` 目录；
- **抖音 Chrome 扩展**：扫描抖音网页版当前已经加载的私信表情，
  排除头像、封面和普通页面图片，下载 PNG、GIF、WebP、JPEG 等原始文件。

桌面程序只读取 QQ 的
`nt_qq\nt_data\Emoji\personal_emoji\Ori`，不会修改 QQ 数据库。抖音扩展只处理
当前页面已经加载的图片，不读取 Cookie，也不会上传聊天内容。

主要目录：

```text
emoji_bridge/              Windows 桌面程序
emoji-bridge-extension/    抖音 Chrome 扩展
tests/                     Python 与 JavaScript 测试
library/                   本地导出的表情，不会提交到 Git
```

启动桌面程序：

```powershell
python -m pip install -r requirements.txt
python run_emoji_bridge.py
```

Windows 用户也可以直接双击 `启动表情中转站.cmd`。

## 抖音扩展安装教程

### 1. 准备扩展文件夹

1. 启动“表情中转站”；
2. 打开顶部的“抖音扩展”工作区；
3. 点击“获取 / 更新扩展”；
4. 等待程序显示“扩展准备与 manifest 校验已完成”；
5. 点击“打开扩展文件夹”。

需要加载的是里面直接含有 `manifest.json` 的
`emoji-bridge-extension` 文件夹，不要选择 ZIP 或它的上层目录。

如果直接从 Git 仓库运行，也可以使用仓库根目录下的
`emoji-bridge-extension` 文件夹。

### 2. 打开 Chrome 扩展管理页

点击桌面程序中的“复制扩展页地址”。程序会复制：

```text
chrome://extensions/
```

Chrome 出于安全原因不允许外部程序直接打开这个内部页面。程序打开 Chrome
后，请在地址栏按 `Ctrl+V`，再按 `Enter`。

也可以在 Chrome 右上角依次打开：

```text
扩展程序图标 → 管理扩展程序
```

### 3. 加载扩展

1. 打开扩展管理页右上角的“开发者模式”；
2. 点击“加载已解压的扩展程序”；
3. 选择第 1 步准备好的 `emoji-bridge-extension` 文件夹；
4. 确认扩展列表中出现“表情中转站”；
5. 点击 Chrome 工具栏的扩展程序图标，把“表情中转站”固定到工具栏。

### 4. 在抖音私信中使用

1. 打开 [抖音网页版](https://www.douyin.com/)并进入私信；
2. 滚动到需要提取的消息，让目标表情加载到当前网页；
3. 如果抖音页面在安装扩展前已经打开，请先刷新页面；
4. 点击工具栏中的“表情中转站”图标；
5. 点击“扫描当前会话”；
6. 核对格式和动画，选择需要的表情并下载。

下载文件会进入浏览器下载目录下的 `EmojiBridge` 文件夹。尚未滚动加载到网页
中的历史表情无法被扫描。

### 5. 更新扩展

项目代码更新后：

1. 回到桌面程序，重新点击“获取 / 更新扩展”；
2. 打开 `chrome://extensions/`；
3. 找到“表情中转站”，点击卡片上的刷新按钮；
4. 刷新已经打开的抖音页面。

如扩展加载失败，请先确认所选文件夹中直接存在 `manifest.json`。
