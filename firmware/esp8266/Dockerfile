FROM python:3.8-slim-bookworm@sha256:1d52838af602b4b5a831beb13a0e4d073280665ea7be7f69ce2382f29c5a613f
RUN rm -rf /var/lib/apt/lists/* && apt-get update && apt-get install -y --no-install-recommends git make gcc g++ flex bison gperf libncurses5 libtinfo5 cmake ninja-build ca-certificates wget && rm -rf /var/lib/apt/lists/*
ARG SDK_REV=89a3f254b63819035f65d9c5dcdae8864f1a6a8a
RUN git clone --branch v3.4 --depth 1 https://github.com/espressif/ESP8266_RTOS_SDK.git /opt/esp8266 && git -C /opt/esp8266 submodule update --init --depth 1 && test "$(git -C /opt/esp8266 rev-parse HEAD)" = "$SDK_REV"
RUN wget -q https://dl.espressif.com/dl/xtensa-lx106-elf-gcc8_4_0-esp-2020r3-linux-amd64.tar.gz -O /tmp/toolchain.tgz && echo '0a1804b5e2231c6db8b72af6bc2a0f9a5b6994cfba29956d412651109f13fe7e  /tmp/toolchain.tgz' | sha256sum -c - && tar -xzf /tmp/toolchain.tgz -C /opt && rm /tmp/toolchain.tgz
RUN python -m pip install --no-cache-dir 'setuptools<70' 'click==7.1.2' 'pyserial==3.5' 'future==1.0.0' 'cryptography==43.0.3' 'pyparsing==2.3.1' 'pyelftools==0.31'
ENV IDF_PATH=/opt/esp8266
ENV PATH=/opt/xtensa-lx106-elf/bin:${PATH}
COPY patches/mqtt-retain.patch /tmp/mqtt-retain.patch
RUN test "$(git -C /opt/esp8266/components/mqtt/esp-mqtt rev-parse HEAD)" = '01594bf118ae502b5a0ead040446f2be75d26223' && git -C /opt/esp8266/components/mqtt/esp-mqtt apply --check /tmp/mqtt-retain.patch && git -C /opt/esp8266/components/mqtt/esp-mqtt apply /tmp/mqtt-retain.patch
WORKDIR /project/firmware/esp8266
CMD ["make", "-j2", "all"]



