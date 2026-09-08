import datetime as dt
from pathlib import Path
from types import SimpleNamespace as P
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import journey


def photo(hour=10, **kw):
    values = dict(uuid=str(hour), date=dt.datetime(2026, 9, 8, hour, tzinfo=dt.timezone.utc),
                  persons=[], albums=[], title='', place=None, location=(None, None), screenshot=False)
    values.update(kw)
    return P(**values)


class Connections(unittest.TestCase):
    def test_existing_cat_identity_is_not_invented(self):
        named = journey.meaning(photo(persons=['大白']), {}, {'大白'})
        unnamed = journey.meaning(photo(), {'labels': {'cat': .88}}, {'大白'})
        self.assertIn('猫 · 大白', named['tracks'])
        self.assertIn('猫时间线', unnamed['tracks'])
        self.assertNotIn('猫 · 大白', unnamed['tracks'])

    def test_conference_text_and_adjacent_document_connect(self):
        a, b = photo(), photo(11)
        ma = journey.meaning(a, {'text': '项目评审会议议程'}, set())
        mb = journey.meaning(b, {'labels': {'document': .9}}, set())
        entries = journey.connect_meeting_material([(a, ma), (b, mb)])
        self.assertEqual(len(journey.event_buckets(entries)), 1)
        self.assertIn('会议与工作', mb['tracks'])
        self.assertTrue(any('时间关联' in e for e in mb['evidence']))

    def test_far_away_document_does_not_join_meeting(self):
        a, b = photo(location=(30., 120.)), photo(11, location=(35., 120.))
        ma = journey.meaning(a, {'text': '会议议程'}, set())
        mb = journey.meaning(b, {'labels': {'document': .9}}, set())
        journey.connect_meeting_material([(a, ma), (b, mb)])
        self.assertEqual(mb['category'], 'documents')

    def test_gap_splits_events_and_preserves_every_asset_once(self):
        photos = [photo(10), photo(11), photo(18)]
        buckets = journey.event_buckets([(p, journey.meaning(p, {}, set())) for p in photos])
        self.assertEqual([len(b) for b in buckets], [1, 2])
        self.assertEqual(sorted(p.uuid for b in buckets for p, _ in b), sorted(p.uuid for p in photos))

    def test_low_confidence_cat_is_not_a_cat_event(self):
        m = journey.meaning(photo(), {'labels': {'cat': .2}}, set())
        self.assertNotIn('猫时间线', m['tracks'])

    def test_unknown_date_does_not_join_unrelated_photos(self):
        photos = [photo(date=None, uuid='a'), photo(date=None, uuid='b')]
        buckets = journey.event_buckets([(p, journey.meaning(p, {}, set())) for p in photos])
        self.assertEqual(len(buckets), 2)

    def test_duplicate_recommendation_preserves_user_metadata(self):
        keeper = photo(uuid='keep', keywords=['记忆'], hasadjustments=False, ismovie=False, live_photo=False)
        duplicate = photo(uuid='copy', keywords=[], hasadjustments=False, ismovie=False, live_photo=False)
        hashes = {'keep': 'same', 'copy': 'same'}
        self.assertTrue(journey.recommend_duplicate(duplicate, keeper, hashes, False))
        self.assertFalse(journey.recommend_duplicate(keeper, keeper, hashes, False))
        self.assertFalse(journey.recommend_duplicate(duplicate, keeper, hashes, True))
        for attribute, value in [('albums', ['独有相册']), ('description', '独有说明'), ('hasadjustments', True),
                                 ('live_photo', True), ('hidden', True), ('date', photo(11).date)]:
            candidate = P(**vars(duplicate)); setattr(candidate, attribute, value)
            self.assertFalse(journey.recommend_duplicate(candidate, keeper, hashes, False), attribute)


if __name__ == '__main__':
    unittest.main()
