import os
import tempfile

# Dados do app (ini/log) numa pasta temporária, nunca no projeto
os.environ.setdefault("SFF_DATA_DIR", tempfile.mkdtemp(prefix="sff-test-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
