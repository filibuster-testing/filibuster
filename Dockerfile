FROM python:3.9
WORKDIR /app
COPY . . 
RUN make install
CMD ["/usr/local/bin/filibuster", "--server-only"]
EXPOSE 5005
