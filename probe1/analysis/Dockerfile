FROM python@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419

WORKDIR /analysis
COPY probe1/analysis/requirements.txt /analysis/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /analysis/requirements.txt

COPY probe1/scripts/analyze_lean.py /analysis/analyze_lean.py
COPY probe1/scripts/experimentlib.py /analysis/experimentlib.py
COPY probe1/scripts/lean_design.py /analysis/lean_design.py

ENTRYPOINT ["python", "/analysis/analyze_lean.py"]
