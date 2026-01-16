# PicGo 配置指南

tgstate-python 原生支持 [PicGo](https://picgo.github.io/PicGo-Doc/) 及其衍生版（如 PicList），您可以将其配置为自定义图床。

## 1. 准备工作

1.  确保您的 tgstate-python 服务已部署并正常运行。
2.  进入 **系统设置** -> **基础设置**，确保 `BASE_URL` 已正确填写（例如 `https://pan.example.com`）。
3.  如果需要，可以设置一个 `PICGO_API_KEY`（在 `系统设置` -> `PicGo API Key` 中设置），用于免登录上传。

## 2. 安装插件

PicGo / PicList 均无需安装额外插件，直接使用内置的 **Custom (自定义)** 图床插件即可。

## 3. 配置参数

打开 PicGo 设置 -> 图床设置 -> 自定义图床，点击 `+` 新建或编辑：

| 参数名 | 填写内容 | 说明 |
| :--- | :--- | :--- |
| **API地址** | `https://您的域名/api/upload` | 例如 `https://pan.example.com/api/upload` |
| **POST参数名** | `file` | 固定值 |
| **JSON路径** | `url` | 固定值，用于获取返回图片链接 |
| **自定义Body** | `{}` | 留空或默认 `{}` |
| **自定义Header** | `{"x-api-key": "您的API_KEY"}` | 如果没设 Key，这里留空或 `{}` |

> **注意**：
> *   如果您在 tgstate 设置了 `PICGO_API_KEY`，请务必在 **自定义Header** 中填写：`{"x-api-key": "您的密钥"}`。
> *   如果您没设 `PICGO_API_KEY`，PicGo 上传可能会报 401 错误，除非您在浏览器里登录过且 PicGo 能共享 Cookie（通常很难），所以**强烈建议设置 API Key**。

## 4. 测试上传

配置完成后，点击 **确定** 并设为 **默认图床**。随便找张图片上传测试，成功后剪贴板里应该会有类似 `https://pan.example.com/d/AbC123` 的链接。

## 常见问题

### Q: 上传失败，提示 401 Unauthorized？
**A**: 说明鉴权失败。
1. 请检查 tgstate 系统设置里的 `PICGO_API_KEY` 是否已设置。
2. 检查 PicGo 配置里的 **自定义Header** 是否填对：`{"x-api-key": "..."}`（注意是英文双引号）。

### Q: 上传成功，但粘贴的链接不带域名？
**A**: 请检查 tgstate 系统设置里的 `BASE_URL` 是否已填写。如果没有填写，系统只能返回相对路径 `/d/xxx`。
