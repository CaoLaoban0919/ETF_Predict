FROM nginx:1.27-alpine

COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY dashboard/index.html /usr/share/nginx/html/index.html
COPY dashboard/styles.css /usr/share/nginx/html/styles.css
COPY dashboard/app.js /usr/share/nginx/html/app.js
COPY dashboard/agent.js /usr/share/nginx/html/agent.js
COPY output/ /usr/share/nginx/html/data/

# macOS 移植：宿主机文件可能是 700 权限，确保 Nginx 非 root 用户可读取静态资源。
RUN chmod -R a+rX /usr/share/nginx/html

# 图表渲染：构建时固定下载 GitHub 项目的浏览器发行包，运行时不依赖外部 CDN。
RUN mkdir -p /usr/share/nginx/html/vendor \
    && wget -q -O /usr/share/nginx/html/vendor/marked.min.js https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.umd.js \
    && wget -q -O /usr/share/nginx/html/vendor/purify.min.js https://cdn.jsdelivr.net/npm/dompurify@3.2.6/dist/purify.min.js \
    && wget -q -O /usr/share/nginx/html/vendor/mermaid.min.js https://cdn.jsdelivr.net/npm/mermaid@11.12.0/dist/mermaid.min.js \
    && chmod -R a+rX /usr/share/nginx/html/vendor

EXPOSE 80

HEALTHCHECK --interval=20s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O - http://127.0.0.1/healthz | grep -q ok || exit 1
