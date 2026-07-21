# 🧱 LikeC4 Diagram Provenance

These PNG files were exported from the canonical LikeC4 project at:

```text
/home/aaron/code/homelab-docs/architecture/likec4
```

## 🔐 Source revision

- Canonical repository: `https://github.com/Racerx323/homelab-docs`
- Canonical commit at export: `f400adee2dd2910f806931057d2b7e808e58564c`
- LikeC4 version: `1.59.1`
- Export state: clean, committed canonical model synchronized with `origin/main`.

The architecture commit above was merged before the `homelab-dns`
documentation so Erode can resolve the updated canonical model from `main`.

## 📋 Canonical source hashes

```text
81afeea4024625fac0519edb95518e9c85be8d54d063c9f8a006f553fa29b8d3  specification.c4
03fb280e056fe29e76a421657d07a95a8a9ea0079e8cd69dd86eaa620b441f1d  model/actors-and-external.c4
372bdf83e2f599891e00c354ee3efef2e7a75171734eab09f7bad30373d6c13c  model/dns.c4
555755dcada9163baa6b2d233c46f7a68b7c5787e83f62252974acec7224976b  model/unbound-reference.c4
a84c231f59f900fe1022080843c2ba6b1ad21dd37918b85d40da7efb944ca17e  deployment/unbound-reference.c4
675b888d9fe6098fac3b6ba65a33597fc905ad117c0d8b3d4e397e438759ae1d  views/runtime.c4
6009fc6a2ad6be73638b3223464a7b4b6e1817060c067f534ddbe047b9f76061  views/dynamic.c4
99b0b1da29959739f55c0813933675dad470992f647b01065f179a4f8d638d87  views/unbound-reference.c4
```

## 🖼️ Exported view hashes

```text
b73e06e9a49e98c03d7cfe5fd311a3e05fb436d794d6fa080563e7fcc1e3fdfc  dns-ha-dot-query.png
fd962176f7e4bccd19838bae41441710f2936b21cdd7b6d903be10283894ae1d  dns-ha-upgrade.png
46dbe76554abd26192d93ad61ebf5dce286c4791dd025651f5c36351d73fd1db  dns-ha.png
646c390aa59b2b09dbd32f35e4247e4e71463d65a6ea20393b0199847f9a2fca  unbound-pihole-v6-reference.png
728f83aa8535fe50e12426b64c488deb6e90c7d2530fe81fc7946c4fb371a4aa  unbound-recursive-query.png
```

## 🧰 Re-export command

Run from `homelab-docs`:

```bash
likec4 export png --flat --seq --description \
  -f dns-ha \
  -f dns-ha-dot-query \
  -f dns-ha-upgrade \
  -f unbound-pihole-v6-reference \
  -f unbound-recursive-query \
  -o ../homelab-dns/Unbound/docs/assets/likec4 \
  architecture/likec4
```
