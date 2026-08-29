# 自动更新清单

`latest.json` 由 `.github/workflows/release.yml` 在发布成功时自动生成并提交。

- 客户端以清单中的 `version` 判断是否需要升级。
- 安装包固定上传到唯一的 `latest` Release，但文件名包含实际版本号。
- 清单记录安装包 URL、字节数和 SHA-256；客户端不会信任 Release 的 Tag 作为版本号。
- 发布流程先上传并校验资产，最后更新清单，避免客户端看到尚未上传完成的版本。

不要手动修改 `latest.json`，也不要为普通版本发布创建额外 Tag。
