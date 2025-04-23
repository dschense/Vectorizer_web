FROM python:3.10-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    potrace \
    imagemagick \
    ca-certificates \
    wget \
    file \
    tar \
    gzip \
    && rm -rf /var/lib/apt/lists/*

# Install vtracer CLI directly
ARG VTRACER_VERSION=0.6.4 # Use latest version
ARG VTRACER_ARCH=x86_64
# Download .tar.gz, verify, and extract with tar
RUN echo "Downloading vtracer..." && \
wget -q "https://github.com/visioncortex/vtracer/releases/download/${VTRACER_VERSION}/vtracer-${VTRACER_ARCH}-unknown-linux-musl.tar.gz" -O vtracer.tar.gz && \
echo "Download complete. Verifying file type..." && \
file vtracer.tar.gz && \
echo "Extracting archive..." && \
tar -xzf vtracer.tar.gz && \
echo "Moving executable..." && \
mv vtracer /usr/local/bin/vtracer && \
echo "Setting permissions..." && \
chmod +x /usr/local/bin/vtracer && \
echo "Cleaning up..." && \
rm vtracer.tar.gz && \
echo "vtracer installation complete."

# App setup
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# ENV PATH is likely not needed anymore if vtracer is directly in /usr/local/bin,
# which is usually in PATH by default in slim images. Keep it for now just in case.
ENV PATH="/usr/local/bin:${PATH}"

COPY . .

EXPOSE 5000
ENTRYPOINT ["python3", "-u", "app.py"]
