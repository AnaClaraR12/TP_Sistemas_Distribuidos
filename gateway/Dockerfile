# nginx >= 1.27.3 (OSS) suporta "resolve" em upstreams => balanceia réplicas do --scale
FROM nginx:1.28-alpine
ENV NGINX_ENVSUBST_FILTER="^GATEWAY_" \
    GATEWAY_RATE_REPOSITORIO=200r/s \
    GATEWAY_BURST_REPOSITORIO=400 \
    GATEWAY_RATE_LOGIN=30r/m \
    GATEWAY_BURST_LOGIN=40
RUN rm -f /etc/nginx/conf.d/default.conf && mkdir -p /var/cache/nginx/repositorio
COPY nginx.conf /etc/nginx/nginx.conf
COPY templates/ /etc/nginx/templates/
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/gateway/health || exit 1
