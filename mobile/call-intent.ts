/** Conservative local escape hatch for explicit call-ending requests.
 * Other phrasing and contextual requests remain with Live/Astra. Never act on
 * partial transcript deltas: a following negation can change their meaning.
 */
export function explicitCallEnd(text: string): boolean {
  const parts = text.normalize('NFKC').toLowerCase().split(/[、,。.!！?？\n]/);
  return parts.filter(part => part.trim()).slice(-1).some(part => {
    const s = part.replace(/[\s、,]/g, '').replace(/^(?:(?:ok|オーケー|はい|うん|了解|ありがとう|じゃあ|それじゃあ|それじゃ|もう|では|一旦))+/, '');
    return /^(?:この|今の)?(?:(?:電話|通話)(?:を|は)?(?:切って(?:ください|くれ|よ)?|切れ|終了して(?:ください|よ)?|終わりにして(?:ください|よ)?|終わらせて(?:ください|よ)?)|会話(?:を|は)?(?:終了して(?:ください|よ)?|終わりにして(?:ください|よ)?|終わらせて(?:ください|よ)?))$/.test(s);
  });
}

/** Select completed utterances for contextual review, NOT automatic hangup.
 * Bare "cut it" and recognition ambiguity must be judged with the dialogue.
 */
export function needsCallControlReview(text: string): boolean {
  const s = text.normalize('NFKC').replace(/\s/g, '');
  return /(?:電話|通話|会話|接続).*(?:切|きて|終|終了)|(?:待機|また呼ぶ|また後で|おやすみ|さようなら)/.test(s)
    || /^(?:(?:あ|ごめん|ちょっと|もう|じゃあ|一旦|ありがとう)[、。]*)*切って(?:ください|よ|ね)?[。！!]*$/.test(s);
}
