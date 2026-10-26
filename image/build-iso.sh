#!/bin/bash
# 在 Debian/Ubuntu 构建机（或 GitHub Actions）上生成可引导安装 ISO。
# 产物: image/output/EasyRouter-install.iso （UEFI + Legacy）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/image/output"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少工具: $1"; exit 1; }; }

echo "==> 安装构建依赖"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq xorriso isolinux syslinux-common syslinux-utils \
    mtools dosfstools wget rsync ca-certificates dpkg-dev
fi
for t in xorriso wget rsync tar; do need "$t"; done

mkdir -p "$OUT"

echo "==> 获取最新 Debian 13 netinst"
BASE="https://cdimage.debian.org/debian-cd/current/amd64/iso-cd"
SUMS="$(wget -qO- "$BASE/SHA256SUMS")"
ISO_NAME="$(printf '%s\n' "$SUMS" | awk '{print $2}' | grep 'amd64-netinst.iso' | head -1)"
[ -n "$ISO_NAME" ] || { echo "无法确定 Debian ISO 文件名"; exit 1; }
SRC="$WORK/$ISO_NAME"
if [ ! -f "$ROOT/image/cache/$ISO_NAME" ]; then
  mkdir -p "$ROOT/image/cache"
  wget -q --show-progress -O "$SRC" "$BASE/$ISO_NAME"
else
  cp "$ROOT/image/cache/$ISO_NAME" "$SRC"
fi
echo "$SUMS" | grep " $ISO_NAME\$" | (cd "$WORK" && sha256sum -c -)

echo "==> 解压 ISO"
mkdir -p "$WORK/iso"
xorriso -osirrox on -indev "$SRC" -extract / "$WORK/iso" >/dev/null 2>&1
chmod -R u+w "$WORK/iso"
ISO="$WORK/iso"

echo "==> 准备离线依赖包（dnsmasq / conntrack / sshpass 及依赖）"
if ! command -v docker >/dev/null 2>&1; then
  echo "错误：完全离线 ISO 需要 Docker 在 Debian 13 环境中下载依赖包"
  exit 1
fi
EXTRA="$WORK/extras"
mkdir -p "$EXTRA"
docker run --rm -v "$EXTRA:/out" debian:13 bash -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --download-only --reinstall --no-install-recommends \
    dnsmasq-base conntrack sshpass \
    libdbus-1-3 libidn12 libnetfilter-conntrack3 libnfnetlink0 \
    libnftables1 libmnl0 libnftnl11 libjansson4 libreadline8t64 libxtables12 \
    libpam0g libselinux1 libwrap0 libgmp10
  cp /var/cache/apt/archives/*.deb /out/
'
ls "$EXTRA"/*.deb >/dev/null 2>&1 || { echo "离线依赖包下载失败"; exit 1; }
mkdir -p "$ISO/pool/easyrouter"
cp "$EXTRA"/*.deb "$ISO/pool/easyrouter/"
echo "==> 生成 ISO 内置离线 apt 源索引"
( cd "$ISO" && dpkg-scanpackages pool /dev/null 2>/dev/null | gzip -9 > Packages.gz )
[ -s "$ISO/Packages.gz" ] || { echo "生成 Packages.gz 失败"; exit 1; }
cat > "$ISO/Release" <<'EOF'
Origin: EasyRouter
Label: EasyRouter Offline
Suite: stable
Codename: trixie
Architectures: amd64
Components: main
EOF

echo "==> 打包应用与 preseed"
mkdir -p "$WORK/app/EasyRouter"
rsync -a --exclude '.git' --exclude 'data' --exclude '__pycache__' \
  --exclude 'tests/.t-*' --exclude 'image/output' --exclude 'image/cache' \
  "$ROOT/" "$WORK/app/EasyRouter/"
tar -czf "$ISO/easyrouter.tar.gz" -C "$WORK/app" EasyRouter
cp "$ROOT/image/preseed.cfg" "$ISO/preseed.cfg"

echo "==> 配置 Legacy 启动项"
ISOLINUX="$ISO/isolinux/isolinux.cfg"
if [ -f "$ISOLINUX" ]; then
  sed -i -E 's/^default .*/default auto/; s/^timeout .*/timeout 30/; s/^prompt .*/prompt 0/' "$ISOLINUX"
  cat >> "$ISOLINUX" <<'EOF'

label auto
  menu label ^Install EasyRouter (automatic)
  kernel /install.amd/vmlinuz
  append auto=true priority=critical preseed/file=/cdrom/preseed.cfg vga=788 initrd=/install.amd/initrd.gz --- quiet
EOF
fi

echo "==> 配置 UEFI 启动项"
GRUB="$ISO/boot/grub/grub.cfg"
if [ -f "$GRUB" ]; then
  if grep -q '^set default=' "$GRUB"; then
    sed -i 's/^set default=.*/set default=auto/' "$GRUB"
  else
    sed -i '1i set default=auto' "$GRUB"
  fi
  sed -i '1i set timeout=30' "$GRUB"
  cat >> "$GRUB" <<'EOF'

menuentry 'Install EasyRouter (automatic)' --id auto {
  linux /install.amd/vmlinuz auto=true priority=critical preseed/file=/cdrom/preseed.cfg --- quiet
  initrd /install.amd/initrd.gz
}
EOF
fi

echo "==> 重新生成混合启动 ISO"
ISOHDPFX="$(find /usr -name isohdpfx.bin 2>/dev/null | head -1)"
[ -n "$ISOHDPFX" ] || { echo "找不到 isohdpfx.bin"; exit 1; }
EFI_IMG="$ISO/boot/grub/efi.img"
[ -f "$EFI_IMG" ] || { echo "ISO 中缺少 EFI 引导镜像"; exit 1; }
xorriso -as mkisofs -o "$OUT/EasyRouter-install.iso" \
  -isohybrid-mbr "$ISOHDPFX" \
  -c isolinux/boot.cat \
  -b isolinux/isolinux.bin -no-emul-boot -boot-load-size 4 -boot-info-table \
  -eltorito-alt-boot -e boot/grub/efi.img -no-emul-boot \
  -isohybrid-gpt-basdat \
  "$ISO"

cp "$SRC" "$ROOT/image/cache/" 2>/dev/null || true
echo "==> 完成: $OUT/EasyRouter-install.iso"
ls -lh "$OUT/EasyRouter-install.iso"
