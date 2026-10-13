import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

module=importlib.util.spec_from_file_location('pod_agent',Path(__file__).with_name('production_agent.py'))
agent=importlib.util.module_from_spec(module);module.loader.exec_module(agent)

class ProductionAgentTests(unittest.TestCase):
    def test_publication_request_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp)/'job.json';job.write_text(json.dumps({'publication_enabled':True}))
            with self.assertRaisesRegex(ValueError,'REVIEW_ONLY_REQUIRED'):
                agent.run(job,tmp,'missing',Path(tmp)/'out')

    @unittest.skipUnless(os.environ.get('CONTENT_CONTROL_ROOT'),'Content Control checkout required')
    def test_cross_repository_node_python_review_package(self):
        spec={'publication_enabled':False,'paid_generation_enabled':False,'platform':'kdp',
          'metadata':{'title':'Integration Fixture','author':'Test Fixture','language':'en',
                      'description':'Synthetic test input, not a marketplace listing.','keywords':['fixture'],
                      'ai_generated':{'text':False,'images':False,'translations':False}},
          'market_research':[],
          'original_art':{'concept_id':'integration-fixture','size_px':[600,600],
                          'palette':[[0,0,0,255],[80,90,120,255]]},
          'cover_template':{'platform':'kdp','dpi':300,'size_inches':[4.35,2.25],
             'art_box_px':[100,100,300,300],'safe_box_px':[25,25,1200,600],
             'kdp':{'trim_width_inches':2,'spine_width_inches':.1,'bleed_inches':.125,'page_count':2}},
          'interior':{'template':{'platform':'kdp','interior_type':'text_no_bleed','trim_inches':[2,2],
             'page_count':2,'margins_inches':dict(inside=.25,outside=.25,top=.25,bottom=.25),
             'font_size_pt':10,'leading_pt':12},'pages':[{'lines':['First page']},{'lines':['Second page']}]}}
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp)/'job.json';job.write_text(json.dumps(spec))
            out=Path(tmp)/'out'
            r=agent.run(job,os.environ['CONTENT_CONTROL_ROOT'],'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',out)
            self.assertEqual(r['status'],'REVIEW_REQUIRED');self.assertFalse(r['marketplace_ready'])
            for name in ('cover.pdf','interior.pdf','metadata.json','provenance.json','research.json'):
                self.assertTrue((out/'package'/name).is_file())
            self.assertEqual(json.loads((out/'package/metadata.json').read_text()),spec['metadata'])
            # Original art + PDFs and the final package are reproducible across attempts.
            again=agent.run(job,os.environ['CONTENT_CONTROL_ROOT'],'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',Path(tmp)/'again')
            self.assertEqual(r['package_sha256'],again['package_sha256'])
            with self.assertRaisesRegex(ValueError,'OUTPUT_EXISTS'):
                agent.run(job,os.environ['CONTENT_CONTROL_ROOT'],'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',out)

if __name__=='__main__':unittest.main()
