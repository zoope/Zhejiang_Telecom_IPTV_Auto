# Zhejiang Telecom IPTV 自动更新 M3U

本仓库每天从 [LionixQ/Zhejiang_Telecom_IPTV](https://github.com/LionixQ/Zhejiang_Telecom_IPTV) 的 `Zhejiang_Multicast.csv` 读取频道列表，生成 `Zhejiang_Telecom_IPTV.m3u`。GitHub Actions 也可以手动运行（Actions → Update M3U → Run workflow）。

公开 M3U 只保存相对 RTP 地址和相对 Logo 路径，不包含部署域名。由 rtp2httpd 加载后，根据实际访问域名生成播放地址：

- 组播地址：`rtp://组播地址:端口`
- Logo 路径：`/Logo/频道.png`
- EPG：`https://myepg.org/EPG/Zhejiang_Unicast.xml.gz`
- FCC：绍兴电信华为平台 `115.233.42.69:8027`，直播地址附加 `?fcc=115.233.42.69:8027&fcc-type=huawei`
- 单播回看：定期从上游 `Zhejiang_Unicast.csv` 读取 `ChannelURL_rtsp`。已有 `TimeShift=1` 的回放地址保持原来的路径；对于 `TimeShift` 为空或为 `0`、但仍有 `ChannelURL_rtsp` 的新增频道生成回放参数，并统一使用 `/TVOD/` 路径。吉林卫视也固定使用 `/TVOD/`。所有回放地址都附加动态 `playseek`。

订阅地址使用 GitHub Raw：

```text
https://raw.githubusercontent.com/<你的用户名>/<仓库名>/main/Zhejiang_Telecom_IPTV.m3u
```

频道源和地址仅适用于已获得运营商授权的 IPTV 网络环境，请遵守相关服务协议和当地法律法规。
