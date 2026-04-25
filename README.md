# Prefect GitHub Repo

This is the tiny GitHub-ready folder for the Prefect Cloud version of the AWC proxy.

Files:

- `proxy_core.py`
- `proxy_flow.py`
- `local_test.py`
- `requirements.txt`
- `prefect.yaml`

## Before deploying

After uploading this folder to GitHub, edit `prefect.yaml` and replace:

`https://github.com/YOUR_USERNAME/YOUR_REPO.git`

with your real repository URL.

## Local test

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python local_test.py
```

## Prefect Cloud deploy

```bash
prefect work-pool create metar-managed --type prefect:managed
prefect deploy --prefect-file prefect.yaml --pool metar-managed
```

## Trigger a run

```bash
prefect deployment run 'awc-api-proxy-prefect/proxy-request' \
  --param method='"GET"' \
  --param path='"/stations/KPHX.TXT"'
```
