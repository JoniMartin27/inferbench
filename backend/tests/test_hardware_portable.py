"""La detección de hardware no puede depender de APIs que faltan en una plataforma.

MEDIDO en CI (macos-latest, 2026-08-13): `psutil.cpu_freq` **no existe como atributo**
en macOS. `_detect_cpu()` hacía `psutil.cpu_freq()` directo, así que levantaba
AttributeError y tumbaba la cadena `_detect_cpu` → `_detect_static` → `detect_hardware`.
Como `BenchmarkRunner.__init__` llama a `detect_hardware()`, en un Mac fallaba **todo
benchmark**, además del dashboard y el listado de compatibilidad. Cuatro tests de la suite
petaban por esto y nadie lo vio porque CI solo corría en Linux.

Se prueba borrando el atributo (que es exactamente la forma del fallo en macOS) y también
haciendo que levante, que es lo que ocurre en contenedores Linux sin `cpufreq`.

TODOS los `monkeypatch` llevan `raising=False` **a propósito**: tanto `delattr` como
`setattr` exigen por defecto que el atributo YA exista, así que en el propio macOS —donde
no existe— el test petaba con AttributeError antes de llegar a comprobar nada. Medido en
CI: el arreglo de producción estaba bien y era la prueba la que fallaba. Con `raising=False`
el borrado es un no-op donde ya falta (justo el estado que se quiere) y el resto de casos
crean el atributo para simular las plataformas que sí lo traen.
"""

import psutil
import pytest

from core.hardware import _cpu_freq_mhz, _detect_cpu, _detect_static, detect_hardware


@pytest.fixture(autouse=True)
def _sin_cache():
    """`_detect_static` es `lru_cache`: sin limpiarla el test mide una detección vieja."""
    _detect_static.cache_clear()
    yield
    _detect_static.cache_clear()


def test_sin_atributo_cpu_freq_como_en_macos(monkeypatch):
    monkeypatch.delattr(psutil, "cpu_freq", raising=False)

    assert _cpu_freq_mhz() is None
    cpu = _detect_cpu()
    assert cpu.freq_mhz is None
    # Lo importante no es el None: es que el resto de la detección sigue viva.
    assert cpu.logical_cores > 0
    assert detect_hardware().ram_gb > 0


def test_cpu_freq_que_revienta_como_en_contenedores(monkeypatch):
    def explota():
        raise NotImplementedError("cpufreq no disponible")

    monkeypatch.setattr(psutil, "cpu_freq", explota, raising=False)

    assert _cpu_freq_mhz() is None
    assert detect_hardware().cpu.freq_mhz is None


def test_cpu_freq_que_devuelve_none(monkeypatch):
    """Linux sin `/sys/.../cpufreq` devuelve None en vez de levantar."""
    monkeypatch.setattr(psutil, "cpu_freq", lambda: None, raising=False)

    assert _cpu_freq_mhz() is None


def test_cuando_la_plataforma_la_expone_se_usa(monkeypatch):
    """El lado positivo: si el dato existe, tiene que llegar a `CPUInfo`, no perderse."""

    class _Freq:
        max = 4200.0

    monkeypatch.setattr(psutil, "cpu_freq", lambda: _Freq(), raising=False)

    assert _cpu_freq_mhz() == 4200.0
    assert _detect_cpu().freq_mhz == 4200.0
