"""Request-boundary checks without importing synthesis/model dependencies."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parent/'voicestudio'


def load_runner():
    setup_spec=importlib.util.spec_from_file_location('money_factory_voice_setup',ROOT/'setup_runtime.py')
    setup=importlib.util.module_from_spec(setup_spec);setup_spec.loader.exec_module(setup)
    runner_spec=importlib.util.spec_from_file_location('money_factory_voice_runner_test',ROOT/'runner.py')
    runner=importlib.util.module_from_spec(runner_spec)
    # The executable imports its adjacent setup module; isolate that alias
    # from other integrations and restore any previous module afterwards.
    with patch.dict(sys.modules,{'setup_runtime':setup}):
        runner_spec.loader.exec_module(runner)
    return runner


runner=load_runner()


class NarrationRequestTests(unittest.TestCase):
    def request(self,**overrides):
        return {'text':'A short synthetic narration.','publication_enabled':False,
                'paid_generation_enabled':False,**overrides}

    def test_default_and_all_presets(self):
        self.assertEqual(runner.validate_request(self.request()),('A short synthetic narration.','expr-voice-2-f',1.0))
        for voice in runner.VOICES:
            self.assertEqual(runner.validate_request(self.request(voice=voice))[1],voice)

    def test_rejects_generation_scope_expansion(self):
        for overrides in ({'publication_enabled':True},{'paid_generation_enabled':True},
                          {'reference_audio':'other-person.wav'},{'voice':'clone'},
                          {'language':'fr'}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                runner.validate_request(self.request(**overrides))
        for flag in ('publication_enabled','paid_generation_enabled'):
            request=self.request();del request[flag]
            with self.assertRaises(ValueError):runner.validate_request(request)

    def test_rejects_nonfinite_boolean_and_unbounded_speed(self):
        for speed in (True,float('nan'),float('inf'),-.5,0,.74,1.51,'1.0'):
            with self.subTest(speed=speed),self.assertRaises(ValueError):
                runner.validate_request(self.request(speed=speed))
        for speed in (.75,1.5):
            self.assertEqual(runner.validate_request(self.request(speed=speed))[2],speed)

    def test_rejects_empty_unspeakable_and_excess_text(self):
        for text in ('','   ','...123...',None,'a'*1201):
            with self.subTest(text_type=type(text).__name__),self.assertRaises(ValueError):
                runner.validate_request(self.request(text=text))
        self.assertEqual(len(runner.validate_request(self.request(text='a'*1200))[0]),1200)


if __name__=='__main__':unittest.main()
