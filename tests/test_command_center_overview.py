import unittest
from unittest.mock import MagicMock, patch
from app.services import command_center as cc
from app.services import command_center_overview as overview
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock


class ReviewEvidenceTests(unittest.TestCase):
    def test_role_is_added_only_to_owned_hub(self):
        service = MagicMock()
        query = service.supabase.table.return_value.select.return_value.eq.return_value.contains.return_value
        with patch.object(cc, 'ProjectService', return_value=service):
            cc._hub_rooms.clear()
            query.execute.return_value.data = [{'room_id': 'room'}]
            self.assertEqual(cc.room_instructions('room', 'owner'), cc.INSTRUCTIONS)
            self.assertEqual(cc.room_instructions('foreign', 'owner'), '')
            query.execute.assert_called_once()
            cc._hub_rooms.clear()
            query.execute.return_value.data = []
            self.assertEqual(cc.room_instructions('room', 'owner'), '')
            cc._hub_rooms.clear()


if __name__ == '__main__':
    unittest.main()


class Query:
    def __init__(self, rows): self.rows=rows; self.filters=[]; self.count=1000; self.start=0
    def select(self, _): return self
    def eq(self,k,v): self.filters.append(lambda r:r.get(k)==v);return self
    def gt(self,k,v): self.filters.append(lambda r:r.get(k,'')>v);return self
    def in_(self,k,v): self.filters.append(lambda r:r.get(k) in v);return self
    def ilike(self,k,v): self.filters.append(lambda r:v.strip('%').casefold() in r.get(k,'').casefold());return self
    def order(self,k,desc=False): self.rows=sorted(self.rows,key=lambda r:r.get(k,''),reverse=desc);return self
    def limit(self,n): self.count=n;return self
    def range(self,a,b): self.start=a;self.count=b-a+1;return self
    def execute(self):
        rows=[r for r in self.rows if all(f(r) for f in self.filters)]
        return type('Result',(),{'data':rows[self.start:self.start+self.count]})()

class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.projects=[{'id':r,'room_id':r,'title':'unrelated title','has_active_run':r=='active'} for r in ('new','old','active')]
        self.messages=[]
        for r in ('new','old','active','foreign'):
            for i in range(6):
                at=self.now-timedelta(days=2 if r=='new' else 60,seconds=6-i)
                self.messages.append({'id':r+str(i),'room_id':r,'content':'truck emblem video' if i==0 else 'plain',
                    'sender_type':'human' if i%2==0 else 'ai','created_at':at.isoformat()})
        # Recent automated output must not reactivate an old room.
        self.messages.append({'id':'auto','room_id':'old','content':'update','sender_type':'ai','created_at':self.now.isoformat()})
        self.service=MagicMock();self.service.list_projects=AsyncMock(return_value=self.projects)
        self.service.supabase.table.side_effect=lambda table:Query([{**p,'user_id':'owner'} for p in self.projects] if table=='projects' else list(self.messages))
        self.patch=patch.object(overview,'ProjectService',return_value=self.service);self.patch.start();self.addCleanup(self.patch.stop)

    async def test_recent_uses_human_activity_and_active_work_and_four_messages(self):
        result=await overview.recent_conversations('owner')
        self.assertEqual({p['id'] for p in result['projects']},{'new','active'})
        self.assertTrue(all(len(p['messages'])==4 for p in result['projects']))
        self.service.list_projects.assert_awaited_once_with('owner')

    async def test_content_search_finds_old_room_without_title_and_excludes_foreign(self):
        result=await overview.search_conversations('owner',['emblem'])
        self.assertEqual({p['id'] for p in result['projects']},{'new','old','active'})
        self.assertTrue(all(p['messages'][0]['content']=='truck emblem video' for p in result['projects']))

    async def test_failure_is_not_an_empty_success(self):
        self.service.supabase.table.side_effect=RuntimeError('offline')
        result=await overview.recent_conversations('owner')
        self.assertTrue(all(p.get('error') for p in result['projects']))
        with self.assertRaises(RuntimeError):await overview.search_conversations('owner',['emblem'])

    async def test_search_includes_hub_and_bounds_long_matched_content(self):
        self.projects.append({'id':'hub-project','room_id':'hub-room','title':'Done','metadata':{'role':'command_center'}})
        original='a'*9000+'予約確定、翌日キャンセル済み。'+'b'*9000
        self.messages.append({'id':'receipt','room_id':'hub-room','content':original,'sender_type':'ai','created_at':self.now.isoformat()})
        result=await overview.search_conversations('owner',['予約'])
        hub=next(p for p in result['projects'] if p['id']=='hub-project')
        self.assertEqual(hub['project_id'],'hub-project')
        self.assertEqual(hub['room_id'],'hub-room')
        excerpt=hub['messages'][0]
        self.assertTrue(excerpt['truncated'])
        self.assertLess(len(excerpt['content']),1850)
        self.assertIn('翌日キャンセル済み',excerpt['content'])
        self.assertEqual(self.messages[-1]['content'],original)

    async def test_search_respects_project_scope_without_crossing_ownership(self):
        result=await overview.search_conversations('owner',['emblem'],project_id='old')
        self.assertEqual([p['id'] for p in result['projects']],['old'])
        with self.assertRaises(ValueError):
            await overview.search_conversations('owner',['emblem'],project_id='foreign')

    async def test_search_includes_following_correction_without_matching_keywords(self):
        self.messages.extend([
            {'id':'answer','room_id':'new','sender_type':'ai','created_at':self.now.isoformat(),'content':'emblem final selected'},
            {'id':'correction','room_id':'new','sender_type':'human','created_at':(self.now+timedelta(seconds=1)).isoformat(),'content':'Actually, cancel that choice.'},
        ])
        result=await overview.search_conversations('owner',['emblem'],project_id='new')
        context=result['projects'][0]['following_context']
        self.assertEqual(context['after_message_id'],'answer')
        self.assertEqual(context['messages'][0]['id'],'correction')
