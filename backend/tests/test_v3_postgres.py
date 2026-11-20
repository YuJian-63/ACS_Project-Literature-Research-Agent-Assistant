"""Temporary native PostgreSQL integration; no SMTP delivery or arXiv network."""
import hashlib, io, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from uuid import UUID, uuid4
from datetime import datetime, timezone
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from app.config import Settings
from app.main import create_app
from app.db.session import create_database_engine, create_session_factory
from app.db.models import AgentResearch, ResearchPaper, AuthMailOutbox, AuthEmailToken
from app.auth.mail import decrypt_payload
from app.sources.arxiv import ArxivPage, ArxivPaper, DownloadReceipt
from app.workers.parser import ParserWorker
from app.workers.imports import ImportWorker

TARGET=os.environ.get('V3_TEST_DATABASE_URL')

def pdf_bytes():
    writer=PdfWriter();page=writer.add_blank_page(width=200,height=200)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 100 Td (Independent v3 evidence.) Tj ET');page[NameObject('/Contents')]=writer._add_object(stream)
    out=io.BytesIO();writer.write(out);return out.getvalue()

@unittest.skipUnless(TARGET,'Use --postgres for an isolated v3 test database')
class V3PostgresTests(unittest.TestCase):
    def test_account_library_import_and_research(self):
        self.assertRegex(make_url(TARGET).database,r'^literature_v3_test_[0-9a-f]{32}$')
        with tempfile.TemporaryDirectory() as directory:
            settings=Settings(database_url=TARGET,storage_root=Path(directory),arxiv_enabled=True,arxiv_contact_email='test@example.invalid')
            engine=create_database_engine(settings);sessions=create_session_factory(engine)
            config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
            with engine.begin() as connection:
                config.attributes['connection']=connection;command.upgrade(config,'head')
            binary=pdf_bytes()
            metadata=ArxivPaper(external_id='1706.03762v1',title='Isolated source',authors=['Test Author'],abstract='Evidence.',categories=['cs.AI'],published_at=datetime(2020,1,1,tzinfo=timezone.utc),source_updated_at=datetime(2020,1,1,tzinfo=timezone.utc))
            class Source:
                def search(self,q,limit=10,offset=0,**kw):return ArxivPage([metadata],1,offset,limit)
                def fetch_metadata(self,external_id):return metadata
                def download_pdf(self,external_id,destination,deadline=None):
                    destination.write_bytes(binary);return DownloadReceipt(len(binary),hashlib.sha256(binary).hexdigest())
            app=create_app(settings,engine=engine,arxiv_client=Source())
            def register(client,name):
                client.headers.update({'Origin':settings.frontend_public_url});password='v3-private-test-password'
                r=client.post('/api/v1/auth/register',json={'username':name,'email':name+'@example.invalid','password':password});self.assertEqual(r.status_code,202,r.text)
                with sessions() as session:
                    row=session.scalar(select(AuthMailOutbox).join(AuthEmailToken,AuthEmailToken.id==AuthMailOutbox.token_id).order_by(AuthMailOutbox.created_at.desc()))
                    token=decrypt_payload(settings,row.payload_ciphertext)['body'].split('#token=',1)[1].split()[0]
                self.assertEqual(client.post('/api/v1/auth/verify-email',json={'token':token,'password':password}).status_code,200)
                r=client.post('/api/v1/auth/login',json={'username':name,'password':password});self.assertEqual(r.status_code,200,r.text)
                self.assertIn('lra_v3_session',r.cookies);self.assertNotIn('lra_dev_session',r.cookies)
                client.headers['X-CSRF-Token']=r.json()['csrf_token'];return UUID(r.json()['user']['id'])
            with TestClient(app) as first,TestClient(app) as second:
                self.assertEqual(first.get('/ready').status_code,200)
                owner=register(first,'v3_owner');register(second,'v3_other')
                self.assertEqual(first.get('/api/v1/agent-research').json()['total'],0)
                self.assertEqual(first.post('/api/v1/agent-research',json={'question':'Question only','paper_ids':[],'allow_search':True}).status_code,503)
                self.assertEqual(first.post('/api/v1/agent-research',json={'question':'   '}).status_code,422)
                r=first.post('/api/v1/papers',files={'file':('test.pdf',binary,'application/pdf')});self.assertEqual(r.status_code,201,r.text);paper=UUID(r.json()['id'])
                self.assertTrue(ParserWorker(sessions,settings).run_once())
                self.assertEqual(first.get('/api/v1/papers/'+str(paper)).json()['status'],'ready')
                self.assertEqual(first.get('/api/v1/papers/'+str(paper)+'/file').content,binary)
                self.assertEqual(second.get('/api/v1/papers/'+str(paper)+'/file').status_code,404)
                research=uuid4()
                with sessions.begin() as session:
                    session.add(AgentResearch(id=research,user_id=owner,question='Evidence?',status='succeeded',result={'answer':'Result'}));session.flush()
                    session.add(ResearchPaper(research_id=research,paper_id=paper,user_id=owner,selection_order=0))
                self.assertEqual(first.get('/api/v1/agent-research').json()['total'],1)
                self.assertEqual(second.get('/api/v1/agent-research').json()['total'],0)
                self.assertEqual(second.get('/api/v1/agent-research/'+str(research)).status_code,404)
                self.assertEqual(second.delete('/api/v1/agent-research/'+str(research)).status_code,404)
                self.assertEqual(first.delete('/api/v1/papers/'+str(paper)).status_code,409)
                with sessions.begin() as session:session.get(AgentResearch,research).status='running'
                self.assertEqual(first.delete('/api/v1/agent-research/'+str(research)).status_code,409)
                with sessions.begin() as session:session.get(AgentResearch,research).status='succeeded'
                self.assertEqual(first.delete('/api/v1/agent-research/'+str(research)).status_code,204)
                self.assertEqual(first.delete('/api/v1/papers/'+str(paper)).status_code,204)
                self.assertEqual(first.get('/api/v1/paper-search',params={'q':'evidence'}).status_code,200)
                r=first.post('/api/v1/paper-imports',json={'provider':'arxiv','external_id':metadata.external_id});self.assertEqual(r.status_code,202,r.text)
                self.assertTrue(ImportWorker(sessions,settings,client_factory=lambda *_:Source()).run_once())
                item=first.get('/api/v1/paper-imports/'+r.json()['id']).json();self.assertEqual(item['status'],'succeeded',item)
                self.assertTrue(ParserWorker(sessions,settings).run_once())
                self.assertEqual(first.get('/api/v1/papers/'+item['paper_id']+'/file').content,binary)
                self.assertEqual(first.delete('/api/v1/papers/'+item['paper_id']).status_code,204)
                self.assertEqual(first.get('/api/v1/tasks').status_code,404)
            engine.dispose()

def run():
    base=make_url(Settings().database_url.get_secret_value())
    if base.database!='literature_v3' or base.port!=55435 or base.host!='127.0.0.1':raise RuntimeError('Expected isolated v3 instance')
    name='literature_v3_test_'+uuid4().hex;admin=create_engine(base.set(database='postgres'),isolation_level='AUTOCOMMIT');created=False
    try:
        with admin.connect() as c:c.exec_driver_sql('CREATE DATABASE "'+name+'"');created=True
        print('Created isolated test database:',name,flush=True)
        env=dict(os.environ,V3_TEST_DATABASE_URL=base.set(database=name).render_as_string(hide_password=False))
        return subprocess.run([sys.executable,str(Path(__file__).resolve()),'-v'],env=env,timeout=120).returncode
    finally:
        if created:
            with admin.connect() as c:c.exec_driver_sql('DROP DATABASE "'+name+'" WITH (FORCE)')
            print('Dropped isolated test database:',name,flush=True)
        admin.dispose()
if __name__=='__main__':
    if sys.argv[1:]==['--postgres']:raise SystemExit(run())
    unittest.main()
