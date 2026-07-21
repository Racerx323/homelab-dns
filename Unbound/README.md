# 📚 Unbound on Debian 12 Raspberry Pi 5

This project documents and configures Unbound for Pi-hole on Debian 12 arm64.
It covers both the existing Pi-hole v5 high-availability deployment and a
clean, single-node Pi-hole v6 reference installation.

Start with the [Unbound documentation index](docs/INDEX.md).

## 🧱 Architecture and drift tracking

The canonical architecture model is maintained in the separate
`homelab-docs/architecture/likec4` project. Published diagram images in this
repository are generated from that model and carry provenance metadata under
`docs/assets/likec4`.

The advisory `Architecture Drift Check` pull-request workflow compares this
repository with that canonical model through Erode. Configure the repository
secret `GEMINI_API_KEY` before enabling the workflow. If `homelab-docs` is
private, also provide a read-only model-repository token as described in the
central Erode installation guide.

Merge the corresponding `homelab-docs` model change before the `homelab-dns`
documentation change so the workflow's `model-ref: main` sees the intended
architecture.

Local verification from this repository uses:

```bash
erode-drift --branch main
```
