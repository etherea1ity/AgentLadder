#!/usr/bin/env bash
# Bootstrap the AgentLadder Python environment on the HKU login gateway.

set -euo pipefail

readonly REMOTE_ROOT="/userhome/cs2/u3665453/AgentLadder"
readonly VENV_DIR="${REMOTE_ROOT}/.venv"
readonly BOOTSTRAP_VENV="${REMOTE_ROOT}/.bootstrap-venv"
readonly UV_PYTHON_INSTALL_DIR="${REMOTE_ROOT}/.python"
readonly UV_CACHE_DIR="${REMOTE_ROOT}/.cache/uv"
export UV_PYTHON_INSTALL_DIR UV_CACHE_DIR

case "$(realpath -m "${REMOTE_ROOT}")" in
  /userhome/cs2/u3665453/AgentLadder) ;;
  *)
    echo "Refusing unexpected remote root: ${REMOTE_ROOT}" >&2
    exit 2
    ;;
esac

if [[ "$(hostname)" != gpu2gate* ]]; then
  echo "This bootstrap is intended for an HKU GPU Farm login gateway." >&2
  exit 2
fi

if [[ -z "${AGENTLADDER_SOURCE_DIR:-}" ]]; then
  echo "AGENTLADDER_SOURCE_DIR must name the inspected, versioned deployment." >&2
  exit 4
fi
source_dir="$(realpath "${AGENTLADDER_SOURCE_DIR}")"
case "${source_dir}" in
  /userhome/cs2/u3665453/AgentLadder/deployments/*) ;;
  *)
    echo "Refusing source outside the AgentLadder deployments directory: ${source_dir}" >&2
    exit 4
    ;;
esac

python_bin="${AGENTLADDER_PYTHON:-}"
if [[ -z "${python_bin}" ]]; then
  for candidate in python3.11 /usr/bin/python3.11; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      python_bin="$(command -v "${candidate}")"
      break
    fi
  done
fi

mkdir -p "${REMOTE_ROOT}" "${REMOTE_ROOT}/logs" "${REMOTE_ROOT}/artifacts"
reuse_venv=false
if [[ -x "${VENV_DIR}/bin/python" ]] \
  && [[ "$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" == "3.11" ]]; then
  reuse_venv=true
  echo "Reusing existing project-local Python 3.11 environment: ${VENV_DIR}"
elif [[ -e "${VENV_DIR}" ]]; then
  echo "Refusing to overwrite an existing non-Python-3.11 environment: ${VENV_DIR}" >&2
  exit 3
fi

if [[ "${reuse_venv}" == true ]]; then
  :
elif [[ -n "${python_bin}" ]]; then
  "${python_bin}" -m venv "${VENV_DIR}"
else
  if [[ -f /etc/profile ]]; then
    # Cluster module definitions commonly live in the system login profile.
    set +u
    source /etc/profile
    set -u
  fi
  if command -v module >/dev/null 2>&1; then
    for module_name in python/3.11 python/3.11.9 python/3.11.8; do
      if module load "${module_name}" >/dev/null 2>&1 \
        && command -v python3.11 >/dev/null 2>&1; then
        python_bin="$(command -v python3.11)"
        break
      fi
    done
  fi
  if [[ -n "${python_bin}" ]]; then
    "${python_bin}" -m venv "${VENV_DIR}"
  else
    # The HKU gateway currently exposes Python 3.10 without ensurepip. Use it
    # only to install a project-local uv bootstrapper, then let uv install a
    # managed Python 3.11 strictly below the AgentLadder remote root.
    # Debian creates the directory before reporting missing ensurepip. Treat a
    # nonzero venv status as recoverable only when its Python executable exists.
    set +e
    /usr/bin/python3 -m venv "${BOOTSTRAP_VENV}"
    bootstrap_venv_status=$?
    set -e
    if [[ ${bootstrap_venv_status} -ne 0 \
      && ! -x "${BOOTSTRAP_VENV}/bin/python" ]]; then
      echo "Python 3.10 could not create even a bootstrap interpreter." >&2
      exit 3
    fi
    if [[ ! -x "${BOOTSTRAP_VENV}/bin/pip" ]]; then
      curl -fsSLo /tmp/get-pip-u3665453-agentladder.py https://bootstrap.pypa.io/get-pip.py
      "${BOOTSTRAP_VENV}/bin/python" /tmp/get-pip-u3665453-agentladder.py
    fi
    "${BOOTSTRAP_VENV}/bin/pip" install --no-cache-dir "uv>=0.8,<1"
    "${BOOTSTRAP_VENV}/bin/uv" --version
    "${BOOTSTRAP_VENV}/bin/uv" python install 3.11
    managed_python="$("${BOOTSTRAP_VENV}/bin/uv" python find \
      --python-preference only-managed 3.11)"
    case "$(realpath "${managed_python}")" in
      "${UV_PYTHON_INSTALL_DIR}"/*) ;;
      *)
        echo "uv selected Python outside the project-local install root: ${managed_python}" >&2
        exit 3
        ;;
    esac
    "${BOOTSTRAP_VENV}/bin/uv" venv --python "${managed_python}" --seed "${VENV_DIR}"
  fi
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Python 3.11 environment creation did not produce ${VENV_DIR}/bin/python" >&2
  exit 3
fi
if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
  curl -fsSLo /tmp/get-pip-u3665453-agentladder.py https://bootstrap.pypa.io/get-pip.py
  "${VENV_DIR}/bin/python" /tmp/get-pip-u3665453-agentladder.py
fi
"${VENV_DIR}/bin/python" --version
if [[ "$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.11" ]]; then
  echo "The isolated training environment is not Python 3.11." >&2
  exit 3
fi
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu124
"${VENV_DIR}/bin/pip" install -e "${source_dir}[dev]"
"${VENV_DIR}/bin/python" - <<'PY'
import sys
import torch

assert sys.version_info[:2] == (3, 11), sys.version
print("python", sys.version.split()[0])
print("torch", torch.__version__)
print("cuda_runtime", torch.version.cuda)
print("gateway_cuda_available", torch.cuda.is_available())
PY

echo "Gateway bootstrap complete. No training was run."
