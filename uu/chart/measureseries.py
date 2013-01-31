import math

from Acquisition import aq_parent, aq_inner
from plone.dexterity.content import Item
from plone.uuid.interfaces import IUUID
from zope.component.hooks import getSite
from zope.interface import implements

from uu.chart.data import NamedDataPoint, TimeSeriesDataPoint
from uu.chart.interfaces import IMeasureSeriesProvider
from uu.chart.interfaces import INamedSeriesChart
from uu.chart.interfaces import provider_measure, resolve_uid
from uu.chart.interfaces import AGGREGATE_FUNCTIONS, AGGREGATE_LABELS


class MeasureSeriesProvider(Item):
    
    implements(IMeasureSeriesProvider)
    
    def pointcls(self):
        """
        Use re-acquisition of self via catalog to ensure proper 
        acquisition wrapping, get point class to use based on the
        acquisition parent (chart) type containing this provider.
        """
        own_uid = IUUID(self)
        wrapped = resolve_uid(own_uid)
        if wrapped is None:
            return TimeSeriesDataPoint  # fallback!
        parent = aq_parent(aq_inner(self))
        if INamedSeriesChart.providedBy(parent):
            return NamedDataPoint
        return TimeSeriesDataPoint
    
    def summarize(self, points):
        items = [(point.identity(), point) for point in points]
        keys = zip(*items)[0]
        if len(keys) == len(set(keys)):
            return points  # no duplicate points for each key
        strategy = getattr(self, 'summarization_strategy', 'AVG')
        if strategy == 'LAST':
            return dict(items).values()  # dict() picks last on collision
        if strategy == 'FIRST':
            return dict(reversed(items)).values()
        if strategy == 'IGNORE':
            # return only points without duplicated keys
            return [v for k,v in items if keys.count(k) == 1]
        if strategy in AGGREGATE_FUNCTIONS:
            sorted_uniq_keys = []
            fn = AGGREGATE_FUNCTIONS.get(strategy)
            keymap = {}
            for k,v in items:
                if math.isnan(v.value):
                    continue  # skip NaN values
                if k not in keymap:
                    sorted_uniq_keys.append(k)  # only once
                    keymap[k] = []
                keymap[k].append(v.value)  # sequence of 1..* values per key
            pointcls = self.pointcls()
            label = dict(AGGREGATE_LABELS).get(strategy)
            result = []
            for k in sorted_uniq_keys:
                vcount = len(keymap[k])
                note = u''
                if vcount > 1:
                    note = u'%s of %s values found.' % (label, vcount)
                result.append(pointcls(k, fn(keymap[k]), note=note))
            return result
        return points  # fallback
    
    @property
    def data(self):
        measure = provider_measure(self)
        if measure is None:
            return []
        group = measure.group()
        dataset_uid = getattr(self, 'dataset', None)
        topic = resolve_uid(dataset_uid)
        if getattr(topic, 'portal_type', None) != 'Topic':
            return []  # no topic or wrong type
        infos = measure.dataset_points(topic)  # list of info dicts
        if not infos:
            return []
        pointcls = self.pointcls()
        _key = lambda info: info.get('start')  # datetime.date
        if pointcls == NamedDataPoint:
            _key = lambda info: info.get('title')
        _point = lambda info: pointcls(
            _key(info),
            info.get('value'),
            note=measure.value_note(info),
            uri=info.get('uri', None),
            )
        all_points = map(_point, infos)
        return self.summarize(all_points)

