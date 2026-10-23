from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_real_app_default_and_dataset_switch():
    app = AppTest.from_file(APP, default_timeout=90).run()
    assert not app.exception
    assert app.title[0].value == "Road networks. Better questions."
    assert any("REAL ROAD SNAPSHOT" in x.value for x in app.info)
    assert len(app.metric) >= 6
    assert any("3,793" == x.value for x in app.metric)
    app.sidebar.selectbox[0].set_value("Synthetic offline demo").run()
    assert not app.exception
    assert any("SYNTHETIC" in x.value for x in app.info)


def test_app_invalid_selection_and_weights():
    app = AppTest.from_file(APP, default_timeout=90).run()
    app.multiselect[0].set_value([]).run()
    assert not app.exception
    assert any("distinct" in x.value for x in app.warning)
    labels = {"Connectivity importance", "Closure detour", "Disconnection loss"}
    for slider in app.sidebar.slider:
        if slider.label in labels:
            slider.set_value(0.0)
    app.run()
    assert not app.exception
    assert any("weights" in x.value for x in app.error)
