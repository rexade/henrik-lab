FROM alpine:latest
COPY --from=filebrowser/filebrowser:v2.31.2 /filebrowser /bin/filebrowser
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
