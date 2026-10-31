import pytest
from app.services.voice_interruption import Interruption


def event(side, start, end, text='言葉'):
    return dict(type=f'session.{side}_transcript.delta', start_ms=start, end_ms=end, delta=text)


def test_overlap_signals_once_and_next_turn_can_interrupt():
    i=Interruption()
    assert not i.observe(event('output', 1000, 1200))
    assert i.observe(event('input', 1100, 1300, 'ちょっと'))
    assert not i.observe(event('input', 1300, 1500, '質問がある'))
    assert not i.observe(event('input', 1100, 1300))
    i.observe(event('output', 4000, 4200))
    assert i.observe(event('input', 4100, 4300, '別の話だけど'))


def test_silence_and_invalid_timestamps_do_not_interrupt():
    i=Interruption()
    assert not i.observe(event('input', 100, 200))
    i.observe(event('output', 1000, 1200))
    assert not i.observe(event('input', 1100, 1300, ' '))
    assert not i.observe(event('input', None, 1300))
    assert not i.observe(event('input', 3000, 3200))


@pytest.mark.asyncio
async def test_only_frontend_steering_not_work_or_canned_reply():
    i=Interruption(); sent=[]; records=[]
    async def send(e): sent.append(e)
    i.observe(event('output', 1000, 1200))
    await i.handle(event('input', 1100, 1300, 'その前に質問'),send,lambda *a,**kw: records.append((a,kw)))
    assert len(sent)==1 and sent[0]['type']=='session.instructions.append'
    assert '聞いてます' not in sent[0]['content']
    assert records[0][1]['input_end_ms']==1300


def test_delayed_question_tail_does_not_cut_off_its_answer():
    i = Interruption()
    i.observe(event('output', 1000, 1200))
    assert not i.observe(event('input', 2200, 2400, '何を'))
    assert not i.observe(event('input', 2400, 2600, 'お願いしたか'))
    i.observe(event('output', 2800, 3000, 'はい、今の'))
    assert not i.observe(event('input', 2600, 2800, '覚えてる'))
    # A genuinely new utterance still interrupts the answer.
    i.observe(event('output', 4000, 4200))
    assert i.observe(event('input', 4100, 4300, 'ちょっと待って'))
