FROM gmag11/metatrader5_vnc:latest

# Copy bridge server
COPY mt5_bridge_server.py /app/mt5_bridge_server.py

# Patch start.sh:
# 1. Disable the broken rpyc/mt5linux server (replace with no-op echo)
# 2. Append Flask bridge startup at the END of start.sh
#    (start.sh runs as the main service, so background processes survive)
RUN sed -i 's|python3 -m mt5linux.*python.exe.*|echo "[JSR] rpyc server disabled - using Flask bridge instead"|g' /Metatrader/start.sh && \
    echo '' >> /Metatrader/start.sh && \
    echo '# === JSR Flask Bridge ===' >> /Metatrader/start.sh && \
    echo 'echo "[JSR] Installing Flask in Wine Python..."' >> /Metatrader/start.sh && \
    echo '$wine_executable python.exe -m pip install -q flask 2>/dev/null' >> /Metatrader/start.sh && \
    echo 'echo "[JSR] Starting Flask MT5 bridge (90s startup delay built-in)..."' >> /Metatrader/start.sh && \
    echo '$wine_executable python.exe /app/mt5_bridge_server.py &' >> /Metatrader/start.sh && \
    echo 'echo "[JSR] Flask bridge PID: $!"' >> /Metatrader/start.sh && \
    echo "[JSR] Patched start.sh: disabled rpyc, added Flask bridge"
