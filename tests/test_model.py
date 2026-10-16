import pytest

from printprep.model import (ADJUST_RANGES, BUILTIN_PRESETS, Adjust, Edit, Settings, combined_adjust, migrate_v1,
                             mm_to_px)


def test_builtin_presets_are_valid_and_grouped():
    groups = []
    for key, preset in BUILTIN_PRESETS.items():
        preset['settings'].validate(check_icc=False)
        if not groups or groups[-1] != preset['group']:
            groups.append(preset['group'])
    assert len(groups) == len(set(groups)), 'groups must be contiguous in the list'


def test_print_size_pixels_follow_ppi():
    s = Settings(size_mode='print', width_mm=102, height_mm=152, dpi=300)
    assert s.target_pixels() == (1205, 1795)
    assert mm_to_px(25.4, 300) == 300


@pytest.mark.parametrize('change, message', [
    (dict(format='JPEG', bit_depth=16), 'JPEG'),
    (dict(size_mode='original', border_mm=3), 'Поля'),
    (dict(quality=101), 'Качество'),
    (dict(dpi=10), 'PPI'),
    (dict(output_space='ICC', icc_path=''), 'ICC'),
    (dict(upscaler='magic'), 'нейросеть'),
])
def test_validation_messages(change, message):
    with pytest.raises(ValueError, match=message):
        Settings(**change).validate()


def test_adjust_ranges_validated():
    with pytest.raises(ValueError):
        Settings(adjust=Adjust(exposure=5)).validate()
    with pytest.raises(ValueError):
        Settings(adjust=Adjust(look='nope')).validate()


def test_roundtrip_dict_ignores_unknown_keys():
    s = Settings(size_mode='pixels', pixel_width=3840, pixel_height=2160, adjust=Adjust(auto=True, shadows=20))
    data = s.to_dict()
    data['future_option'] = 1
    data['adjust']['future'] = 2
    assert Settings.from_dict(data) == s


def test_migrates_v1_settings():
    old = dict(width_mm=100, height_mm=150, size_mode='print', dpi=300, fit='contain', format='TIFF', quality=95,
               output_space='sRGB', icc_path='', intent=1, auto_enhance=False, sharpen=True, smart_crop=False,
               allow_upscale=True, enhancement_preset='balanced', enhancement_strength=.5, shadows=.4, highlights=.2,
               clarity=.1, vibrance=.2, warmth=.1, tint=0, chroma_denoise=0, auto_wb=False, auto_tone=True,
               upscaler='fsrcnn', neural_strength=.6)
    s = Settings.from_dict(old)
    s.validate(check_icc=False)
    assert s.sharpen == 'glossy' and s.upscaler == 'fsrcnn' and s.neural_strength == 60
    assert s.adjust.shadows == 20 and s.adjust.highlights == -10 and s.adjust.auto


def test_migrates_v1_edit():
    e = Edit.from_dict(dict(rotation=90, fit='cover', center_x=.3, center_y=.5, zoom=1.5, manual_crop=True,
                            exposure=.5, contrast=1.2, saturation=.8, use_neural=True, neural_strength=.5))
    assert e.rotation == 90 and e.neural is True
    assert e.offsets == {'exposure': .5, 'contrast': 20, 'saturation': -20}


def test_edit_validation_and_defaults():
    assert Edit().is_default()
    assert not Edit(offsets={'exposure': .3}).is_default()
    with pytest.raises(ValueError):
        Edit(rotation=45).validate()
    with pytest.raises(ValueError):
        Edit(offsets={'unknown': 1}).validate()


def test_combined_adjust_clamps_to_slider_range():
    s = Settings(adjust=Adjust(shadows=90))
    a = combined_adjust(s, Edit(offsets={'shadows': 50, 'exposure': -1}))
    assert a.shadows == ADJUST_RANGES['shadows'][2] and a.exposure == -1
