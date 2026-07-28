# 表情中转站 Emoji Bridge

本地工具，用来在抖音网页版、QQ 和微信之间中转静态/动态表情。它分成两个组件：

- Chrome 扩展：从抖音网页版聊天中提取已经加载的原始表情；
- Windows 桌面端：自动发现 QQ / 微信数据目录，检查真实格式、预览动画并复制到统一表情库。

所有处理都在本机完成。工具不读取 Cookie、不上传聊天内容，也不修改 QQ 或微信数据库。

## 当前能力（以实测为准）

| 来源 | 自动找路径 | 提取原件 | 当前状态 |
| --- | --- | --- | --- |
| 抖音网页版 | 不需要客户端路径；读取 Chrome 下载目录 | PNG / GIF / WebP / JPEG | 桌面端可下载扩展并显示安装教程；安装后负责提取，桌面端负责预览与转换 |
| QQ NT 9.9 | 是 | 只读取表情面板心形“喜欢”对应的 `Emoji\personal_emoji\Ori` | 已验证喜欢列表 118 项，不混入聊天缓存 |
| 微信 4.1 | 自动缓存读取不可用；支持官方导出接收箱 | 静态图片消息 | 本机缓存已加密；已实测消息右键“另存为…”，接收箱可扫描预览；动态收藏待验证 |

目标平台暂时采用安全的官方流程：把本地表情库中的文件发送到目标聊天，再“添加/收藏为表情”。不直接写客户端数据库。

## 路径如何适配不同用户

桌面端不会写死账号和盘符：

1. 微信运行时优先读取进程参数 `--wechat-files-path`；
2. 再读取客户端配置与 Windows 标准目录；
3. QQ 枚举 Windows 盘符及常见用户目录；
4. QQ 只接受内部确实含有 `nt_qq\nt_data\Emoji` 的目录；
5. 微信只接受确实含有 `business\emoticon` 或 `cache\...\Emoticon` 的目录；
6. 多账号按最近缓存活动排序；
7. 自动发现失败时可手动选一次，路径保存到 `%APPDATA%\EmojiBridge\config.json`。

账号只在本地显示，工具不要求用户填写 QQ 号或微信号。

## 启动桌面端

克隆或下载仓库后，双击项目目录中的：

`启动表情中转站.cmd`

也可以运行：

```powershell
cd <Emoji-download 项目目录>
python -m pip install -r requirements.txt
python run_emoji_bridge.py
```

操作方法：

1. 在顶部选择“抖音网页 / QQ / 微信”来源；
2. 工具自动选择最近活动的账号，也可切换账号；QQ 默认只显示“我的表情”；
3. 选择表情，右侧核对真实格式、尺寸、帧数和动画预览；
4. 可按住 `Ctrl` / `Shift` 多选，或点击“全选当前”；
5. 输出到 QQ / 抖音时选“保留原件”，输出到微信时选“微信兼容版”；
6. 文件保存到项目的 `library`；微信兼容版进入其 `wechat-ready` 子目录；
7. 从该目录发送到目标平台，再使用客户端的添加/收藏功能。

微信作为来源时：

1. 把“我添加的表情”发送到文件传输助手；
2. 右键已发送的消息，选择“另存为…”；
3. 保存到项目的 `library\wechat-inbox`；
4. 回到工具的“微信”页点击“重新发现”，即可预览并迁往 QQ / 抖音。

上述菜单已对静态图片消息实测；动态收藏表情能否同样保存，尚未验证，不在当前完成范围内。

## 安装抖音网页扩展

推荐从桌面端顶部进入“抖音网页”，点击“下载 Chrome 扩展”。程序会：

1. 从本仓库下载最新版源码压缩包；
2. 只解压 `emoji-bridge-extension`；
3. 检查 `manifest.json` 是否为有效 Manifest V3 扩展；
4. 显示最终扩展文件夹和完整安装票据。

随后手动完成：

1. Chrome 打开 `chrome://extensions/`；
2. 开启右上角“开发者模式”；
3. 点击“加载已解压的扩展程序”；
4. 选择程序显示的 `emoji-bridge-extension` 文件夹；
5. 固定扩展图标并刷新已经打开的抖音页面。

不要选择 ZIP，也不要选择它的上层 `EmojiBridge` 文件夹。直接把 ZIP 或文件夹拖入扩展页在不同 Chrome 版本中并不稳定，因此不是本项目的标准安装方式。

开发者也可以直接选择仓库内的 `emoji-bridge-extension` 文件夹。

在抖音私信中滚动到目标表情，打开“表情中转站”，扫描并下载。文件默认进入 Chrome 下载目录的 `EmojiBridge` 文件夹，桌面端的“抖音网页”来源会自动读取这里。

## 已知边界

- 抖音扩展只能读取当前网页已经加载到 DOM 的聊天表情。
- 微信 4.1 的本地表情文件已加密；桌面端不读取或伪装密文，只扫描用户通过微信官方“另存为…”保存到接收箱的图片。
- QQ / 微信没有稳定公开的个人表情批量导入接口，因此不直接改数据库。
- 微信兼容版会把最长边限制为 240 px、动态 GIF 控制在 1 MB 内，并复核动画和透明背景；QQ / 抖音默认保留原件。

## 验证

```powershell
python -m pytest .\tests\test_desktop_core.py -q
node --test .\tests\core.test.cjs
python -m py_compile .\emoji_bridge\core.py .\emoji_bridge\app.py
node --check .\emoji-bridge-extension\core.js
node --check .\emoji-bridge-extension\background.js
node --check .\emoji-bridge-extension\content.js
```
