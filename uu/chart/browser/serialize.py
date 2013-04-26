"""
chart views for generating JSON representation of chart data

JSON structure pseudo-UML
-------------------------

Note: properties marked with multiplicity [0..1] either have a typed
      value or are null.  These properties with optional values may
      also be omitted (undefined) from the JSON payload.

      Rendering code should have suitable defaults for ommited
      configuration and optional metadata.

      Date values will be formatted to ISO 8601 with microseconds removed.
      (jqplot understands this format, as do many other parsers).

 _________________________________       _____________________
| Multi-series chart              | ,   | Time-series chart   |  subclass adds
+---------------------------------+/|___+---------------------+  string date
| title : String                  |\|   | frequency : String  |  Ex: 'monthly'
| description : String      [0..1]| `   | start : String      |  start, end,
| css : String              [0..1]|     | end : String        |  frequency,
| x_label : String          [0..1]|     | labels : Object     |  labels fields
| y_label : String          [0..1]|     | auto_crop : Boolean |
| chart_type : String       [0..1]|     '---------------------'
| units : String            [0..1]|
| goal : Number             [0..1]|   Common goal; omit if None or hidden.
| goal_color : String       [0..1]|   include IFF configured, goal not hidden
| x_axis_type : String      [0..1]|   Either 'date' or omitted.
| legend_location : String  [0..1]|   null ==> hide legend
| legend_placement : String [0..1]|
| aspect_ratio : Array      [0..1]|   Optional array of [W,H] numbers (ratio)
'---------------------------------'     Should be omitted when chart is not
       1 /%\                            configued to tie height to width.
         \%/
          Y
          |
    0..*  | series                  (Array of objects)
 _________!___________________
|  Data series                |     SERIES WITH NO/EMPTY DATA WILL BE OMITTED
+-----------------------------+
| title : String              |
| description : String  [0..1]|
| units  : String       [0..1]|
| line_width : Number   [0..1]|       (note: line_width=0 : do not show line,
| color : String        [0..1]|               however, markers may be shown).
| marker_color : Number [0..1]|
| marker_width : Number [0..1]|       (integer value)
| marker_size : Number  [0..1]|       (floating point value)
| marker_style : String [0..1]|
| range_min : Number    [0..1]|       (y-axis min/max)
| range_max : Number    [0..1]|
| show_trend : String   [0..1]|     'true' or 'false' in JSON
| trend_width : Number  [0..1]|
| trend_color : String  [0..1]|     if empty, default same as color
| goal : Number         [0..1]|
| display_format:String [0..1]|     == '%%.%if' % display_precision
| break_lines : Boolean       |     'true'/'false': display null points?
'-----------------------------'
       1 /%\
         \%/
          Y
          |
    0..*  | data                    Array of two-item key-value pairs (arrays)
 _________!_____________            of name or date keys and point objects.
| Data point Object     |
+-----------------------+
| key : String          |       (key is either name or Date representation)
| value : Number        |       Number or {} null object as sentinel for NaN
| title : String  [0..1]|       Label for key, may be same as key.
| note : String   [0..1]|
| uri : String    [0..1]|
'-----------------------'

Notes, enumerated choices:

 * Time series frequency:
    'monthly' (default)
    'weekly'
    'yearly'
    'quarterly'

 * Chart types:
    'line' (default)
    'bar'

 * Legend placement:
    'inside'
    'outside'
    'tabular'

"""

from datetime import date, datetime
from fractions import Fraction
import json
import math
import re

from uu.chart.interfaces import ITimeSeriesChart

from datelabel import DateLabelView
from utils import withtz


def stripms(stamp):
    """
    Given ISO 8601 datestamp, strip out any milliseconds in representation
    using a regular expression safe for either stamps with or stamps
    without milliseconds included.
    """
    stamp_pattern = re.compile('([^.]+)([.][0-9]+)?([+-].*)')
    return stamp_pattern.sub('\g<1>\g<3>', stamp)


def isodate(dt):
    # get datetime (from date or datetime) with user, site, or system tz:
    dt = withtz(dt)
    # copy, normalize to same timezone, such that microseconds are stripped:
    dt = dt.tzinfo.normalize(datetime(*dt.timetuple()[:7], tzinfo=dt.tzinfo))
    return stripms(dt.isoformat())


class ChartJSON(object):
    """Adapter to create JSON for use by view"""

    def __init__(self, context):
        self.context = context
    
    def _series_list(self):
        """Get all series represented as dict"""
        r = []
        for seq in self.context.series():
            series = {}
            # series data is mapping of keys to point objects
            series['data'] = list(
                [(p['key'], p) for p in map(self._datapoint, seq.data)]
                )
            if not series['data']:
                continue  # omit series with no data from JSON output
            for name in (
                'title',
                'description',
                'units',
                'line_width',
                'color',
                'marker_color',
                'marker_size',
                'marker_width',
                'marker_style',
                'range_min',
                'range_max',
                'show_trend',
                'trend_width',
                'trend_color',
                'goal',
                'break_lines',
                    ):
                v = getattr(seq, name, None)
                if v is not None and v != '':
                    if not (name.endswith('color') and
                            str(v).upper() == 'AUTO'):
                        series[name] = v
            # display format via display precision (digits after decimal pt)
            precision = getattr(seq, 'display_precision', 1)
            series['display_format'] = '%%.%if' % precision
            r.append(series)
        return r
    
    def _datapoint(self, point):
        r = {}
        r['key'] = key = point.identity()
        if isinstance(key, date) or isinstance(key, datetime):
            r['key'] = key = isodate(key)
        r['title'] = unicode(point.identity()).title()
        value = None if math.isnan(point.value) else point.value
        r['value'] = value
        if point.note is not None:
            r['note'] = point.note
        if point.uri is not None:
            r['uri'] = point.uri
        return r

    def _chart(self):
        chart_attrs = [
            'title',
            'description',
            'chart_type',
            'units',
            'goal',
            'goal_color',
            'x_label',
            'y_label',
            'legend_placement',
            'legend_location',
            'width',
            'height',
            ]
        timeseries_chart_attrs = [
            'frequency',
            'auto_crop',
            'start',
            'end',
            ]
        context = self.context
        r = {}
        if ITimeSeriesChart.providedBy(context):
            chart_attrs = chart_attrs + timeseries_chart_attrs
            label_view = DateLabelView(context)
            included = label_view.included_dates()
            r['x_axis_type'] = 'date'
            r['auto_crop'] = True  # default, explcit value may disable
            r['labels'] = labels = {}
            for d in included:
                k = label_view.date_to_jstime(d)
                custom = label_view.label_for(d) or None
                if custom is None:
                    labels[k] = label_view.date_to_formatted(d)
                else:
                    labels[k] = custom
        r['series'] = self._series_list()
        if context.chart_styles:
            r['css'] = context.chart_styles
        for name in chart_attrs:
            v = getattr(self.context, name, None)
            if v is not None and v != '':
                if (name.endswith('color') and str(v).upper() == 'AUTO'):
                    continue
                elif isinstance(v, date) or isinstance(v, datetime):
                    r[name] = isodate(v)
                else:
                    r[name] = v
        if not self.context.show_goal and r.get('goal', None):
            del(r['goal'])  # omit if show_goal is false
        if not self.context.show_goal and r.get('goal_color', None):
            del(r['goal_color'])  # superfluous if show_goal is false
        self._set_aspect_ratio(context, r)
        return r
    
    def _set_aspect_ratio(self, context, r):
        height_units = getattr(context, 'height_units', '2:1')
        if height_units == 'px':
            return  # fixed pixels (job of template, so JSON API omits)
        if ':' in height_units:
            r['aspect_ratio'] = map(int, height_units.strip().split(':')[:2])
        if height_units == '%':
            height = getattr(context, 'height', None)
            if not height:
                r['aspect_ratio'] = [2, 1]  # height not specified, use default
            # aproximate a fraction precision about +/- 0.5%
            f = Fraction(1.0 / (height / 100.0)).limit_denominator(20)
            r['aspect_ratio'] = [f.numerator, f.denominator]
    
    def render(self):
        return json.dumps(self._chart(), indent=2)


class ChartJSONView(object):
    """Browser view for JSON representation of chart context"""
    
    def __init__(self, context, request):
        self.context = context
        self.request = request
   
    def __call__(self, *args, **kwargs):
        self.request.response.setHeader('Content-type', 'application/json')
        return ChartJSON(self.context).render()


