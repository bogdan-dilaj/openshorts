#!/usr/bin/env bash

if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
DEFAULT_TARGET="${PROJECT_ROOT}/output/longform_source_mount"

resolve_target_mount() {
  local configured=""
  if [[ -f "${ENV_FILE}" ]]; then
    configured="$(grep -E '^LONGFORM_SOURCE_HOST_DIR=' "${ENV_FILE}" | tail -n1 | cut -d'=' -f2- || true)"
  fi
  configured="${configured%\"}"
  configured="${configured#\"}"
  configured="${configured%\'}"
  configured="${configured#\'}"

  if [[ -z "${configured}" ]]; then
    printf '%s\n' "${DEFAULT_TARGET}"
    return
  fi

  if [[ "${configured}" == ./* ]]; then
    printf '%s\n' "${PROJECT_ROOT}/${configured#./}"
    return
  fi

  if [[ "${configured}" != /* ]]; then
    printf '%s\n' "${PROJECT_ROOT}/${configured}"
    return
  fi

  printf '%s\n' "${configured}"
}

TARGET_MOUNT="${1:-$(resolve_target_mount)}"

if ! command -v lsblk >/dev/null 2>&1; then
  echo "lsblk wurde nicht gefunden."
  exit 1
fi

if ! command -v findmnt >/dev/null 2>&1; then
  echo "findmnt wurde nicht gefunden."
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo wurde nicht gefunden."
  exit 1
fi

if ! command -v mount >/dev/null 2>&1; then
  echo "mount wurde nicht gefunden."
  exit 1
fi

if ! command -v mountpoint >/dev/null 2>&1; then
  echo "mountpoint wurde nicht gefunden."
  exit 1
fi

mkdir -p "${TARGET_MOUNT}"

mapfile -t DEVICE_ROWS < <(
  lsblk -J -o PATH,NAME,RM,HOTPLUG,TRAN,SIZE,FSTYPE,LABEL,MOUNTPOINTS |
    python3 -c '
import json, sys

SYSTEM_MOUNTPOINTS = {"/", "[SWAP]"}
SYSTEM_PREFIXES = ("/home", "/nix", "/tmp", "/boot")
AUTOMOUNT_PREFIXES = ("/run/media/", "/media/")

def is_internal_mountpoint(value):
    if value in SYSTEM_MOUNTPOINTS:
        return True
    return any(value == prefix or value.startswith(prefix + "/") for prefix in SYSTEM_PREFIXES)

def walk(node):
    path = (node.get("path") or "").strip()
    fstype = (node.get("fstype") or "").strip()
    mountpoints = [m.strip() for m in (node.get("mountpoints") or []) if str(m).strip()]
    rm = 1 if node.get("rm") else 0
    hotplug = 1 if node.get("hotplug") else 0
    tran = (node.get("tran") or "").strip()
    label = (node.get("label") or "").strip()
    size = (node.get("size") or "").strip()
    name = (node.get("name") or path).strip()
    has_external_mount = any(mp.startswith(AUTOMOUNT_PREFIXES) for mp in mountpoints)
    has_only_system_mounts = bool(mountpoints) and all(
        is_internal_mountpoint(mp)
        for mp in mountpoints
    )
    if path and fstype and not has_only_system_mounts and (rm or hotplug or tran in {"usb", "sdio"} or has_external_mount):
        print("\t".join([
            path,
            name,
            size or "-",
            fstype,
            label or "-",
            ",".join(mountpoints) or "-",
            tran or "-",
            str(rm),
            str(hotplug),
        ]))
    for child in node.get("children") or []:
        walk(child)

payload = json.load(sys.stdin)
for item in payload.get("blockdevices") or []:
    walk(item)
'
)

if [[ "${#DEVICE_ROWS[@]}" -eq 0 ]]; then
  echo "Keine passenden Datentraeger gefunden."
  echo "Lege Dateien alternativ direkt unter ${DEFAULT_TARGET} ab oder nutze Browser-Upload."
  exit 1
fi

label_for_index() {
  local idx=$1
  local chars=(a b c d e f g h i j k l m n o p q r s t u v w x y z)
  local label=""
  local rem=""
  while (( idx >= 0 )); do
    rem=$(( idx % 26 ))
    label="${chars[$rem]}${label}"
    idx=$(( idx / 26 - 1 ))
  done
  printf '%s' "${label}"
}

SELECTION_LABELS=()

echo
echo "Verfuegbare Datentraeger"
echo "Ziel-Mountpoint: ${TARGET_MOUNT}"
echo

for i in "${!DEVICE_ROWS[@]}"; do
  label="$(label_for_index "${i}")"
  SELECTION_LABELS+=("${label}")
  IFS=$'\t' read -r path name size fstype label mountpoints tran rm hotplug <<<"${DEVICE_ROWS[$i]}"
  selection_label="${SELECTION_LABELS[$i]}"
  printf ' %s) %-12s size=%-8s fs=%-8s label=%-18s mounted=%s\n' "${selection_label}" "${path}" "${size}" "${fstype}" "${label}" "${mountpoints}"
done

echo
read -r -p "Welcher Datentraeger soll auf ${TARGET_MOUNT} gemountet werden? [Buchstabe] " selection
selection="$(printf '%s' "${selection}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

selected_index=-1
for i in "${!SELECTION_LABELS[@]}"; do
  if [[ "${SELECTION_LABELS[$i]}" == "${selection}" ]]; then
    selected_index=$i
    break
  fi
done

if (( selected_index < 0 )); then
  echo "Ungueltige Auswahl."
  exit 1
fi

IFS=$'\t' read -r DEVICE_PATH DEVICE_NAME DEVICE_SIZE DEVICE_FSTYPE DEVICE_LABEL DEVICE_MOUNTPOINTS DEVICE_TRAN DEVICE_RM DEVICE_HOTPLUG <<<"${DEVICE_ROWS[$selected_index]}"

echo
echo "Ausgewaehlt: ${DEVICE_PATH} (${DEVICE_SIZE}, ${DEVICE_FSTYPE}, label=${DEVICE_LABEL})"

CURRENT_TARGET_SOURCE=""
if mountpoint -q "${TARGET_MOUNT}"; then
  CURRENT_TARGET_SOURCE="$(findmnt -n -o SOURCE --target "${TARGET_MOUNT}" 2>/dev/null || true)"
fi

if [[ -n "${CURRENT_TARGET_SOURCE}" ]]; then
  if [[ "${CURRENT_TARGET_SOURCE}" == "${DEVICE_PATH}" ]]; then
    echo "Der ausgewaehlte Datentraeger ist dort bereits gemountet."
    exit 0
  fi
  echo "Auf dem Zielpfad ist bereits gemountet: ${CURRENT_TARGET_SOURCE}"
  read -r -p "Soll das bestehende Mount zuerst ausgehaengt werden? [j/N] " confirm_unmount_target
  if [[ ! "${confirm_unmount_target}" =~ ^[JjYy]$ ]]; then
    echo "Abgebrochen."
    exit 1
  fi
  sudo umount "${TARGET_MOUNT}"
fi

if [[ "${DEVICE_MOUNTPOINTS}" != "-" ]]; then
  IFS=',' read -r -a CURRENT_MOUNTS <<<"${DEVICE_MOUNTPOINTS}"
  for mountpoint in "${CURRENT_MOUNTS[@]}"; do
    [[ -z "${mountpoint}" ]] && continue
    if [[ "${mountpoint}" == "${TARGET_MOUNT}" ]]; then
      continue
    fi
    echo "Partition ist aktuell gemountet auf: ${mountpoint}"
    read -r -p "Soll ${mountpoint} ausgehaengt werden, damit neu auf ${TARGET_MOUNT} gemountet werden kann? [j/N] " confirm_unmount
    if [[ ! "${confirm_unmount}" =~ ^[JjYy]$ ]]; then
      echo "Abgebrochen."
      exit 1
    fi
    sudo umount "${mountpoint}"
  done
fi

echo "Mount wird vorbereitet ..."
sudo mkdir -p "${TARGET_MOUNT}"

mount_with_fallback() {
  if [[ "${DEVICE_FSTYPE}" =~ ^(vfat|msdos|exfat|ntfs|ntfs3|fat|fuseblk)$ ]]; then
    sudo mount -o "uid=$(id -u),gid=$(id -g),umask=022" "${DEVICE_PATH}" "${TARGET_MOUNT}" 2>/dev/null || sudo mount "${DEVICE_PATH}" "${TARGET_MOUNT}"
  else
    sudo mount "${DEVICE_PATH}" "${TARGET_MOUNT}"
  fi
}

mount_with_fallback

if ! mountpoint -q "${TARGET_MOUNT}"; then
  echo "Mount scheint fehlgeschlagen zu sein. ${TARGET_MOUNT} ist kein eigener Mountpoint."
  exit 1
fi

FINAL_SOURCE="$(findmnt -n -o SOURCE --target "${TARGET_MOUNT}" 2>/dev/null || true)"
if [[ "${FINAL_SOURCE}" != "${DEVICE_PATH}" ]]; then
  echo "Mount scheint fehlgeschlagen zu sein. Erwartet: ${DEVICE_PATH}, gefunden: ${FINAL_SOURCE:-<nichts>}"
  exit 1
fi

echo
echo "Fertig."
echo "${DEVICE_PATH} ist jetzt auf ${TARGET_MOUNT} gemountet."
echo "Im Longform Video Editor kannst du danach direkt 'Per Pfad hinzufuegen' nutzen."
echo "Docker-Recreate ist dafuer nicht noetig, solange ${TARGET_MOUNT} deiner LONGFORM_SOURCE_HOST_DIR-Konfiguration entspricht."
