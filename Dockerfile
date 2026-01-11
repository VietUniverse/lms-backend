FROM python:3.11
WORKDIR /app

# Cài đặt Docker CLI (Static Binary - Nhanh hơn apt-get nhiều)
RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-26.1.3.tgz -o docker.tgz && \
    tar xzvf docker.tgz --strip-components 1 -C /usr/local/bin docker/docker && \
    rm docker.tgz && \
    chmod +x /usr/local/bin/docker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
