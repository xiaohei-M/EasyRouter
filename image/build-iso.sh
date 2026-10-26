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
    mtools dosfstools wget rsync ca-certificates
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
