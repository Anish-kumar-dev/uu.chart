"""
uu.chart.interfaces -- narrative summary of components:
  
  * Reports are ordered containers (folders) of one or more charts.
  
  * Charts are made up of data collections and presentation metadata.
  
  * Data collections (and therefore charts) contain a sequence of one or
    more data series.

        Terminology: we use the word "series" in a more colloquial, not
                     strictly mathematic sense: "series" is used
                     synonymously with "sequence" -- in our case a series
                     is a labeled/named sequence, for which each label
                     provides a facet for grouping related data points.
                    
                     In strictly mathematical sense, what we call "points"
                     are relations:
                     
                        value    R           sequencename
                                  pointname
                     
                     and a "series" is a sequence of these relations. 
                    
                     We can also group all values sharing the same point
                     identity/name across multiple sequences as being
                     set members of an equivalence class for that point
                     identity/name:
                    
                        [x]
                           R
                            pointname
                     
                     This is essentially what a multi-line or bar chart
                     presents in horizontal x-axis groupings.  In a way,
                     this is a visualization of faceted classification --
                     whether such facets are dates (as in a chronological
                     time-series) or nominal classifiers.
                     
  * Each series is named and is an iterable sequence of points.
  
  * Points have a unique identity within a series, usually either a name 
    or a date.  This name/identity is does double-duty as an identifier and
    as a title.

    * It is useful to think of each point as a single key/value pair, where
      the key is usually visualized and grouped along the X-axis and the 
      value is usually treated as a Y-axis value.
  
  * Points contain one numeric value each and simple annotation metadata 
    (note, URL) fields.
  
  * Charts can contain presentation metadata for:
  
    * Display for the chart at large.
    
    * Display for one series within the chart.

  * Implementations can store data series intrinsically on the chart, or
    delegate their lookup to other components (e.g. database lookups, index
    queries, traversal to externally stored measures).

  * User experience:

    (a) User creates a report in application.
    
    (b) User visits reports and adds "chart" items to the report.
    
      * User chooses a chart type at this time:
    
        * Named-series chart 
            * May be line or bar chart, configurable.
        
        * Time-series chart:
            * May be line or bar chart, configurable.
    
      * User optionally re-orders chart position in report at creation
        time or any time thereafter.
  
    (c) User visits chart, adds "Data series" to chart:
        
        If chart is time-series, user add a "Time-series sequence"
        
            A type for an externally defined measure, might be called
            "Time-series measure" in the add menu.
        
        If chart is named-series chart, user adds "Named-series sequence"

"""

import operator

from persistent.dict import PersistentDict
from plone.app.textfield import RichText
from plone.directives import form, dexterity
from plone.formwidget.contenttree import ContentTreeFieldWidget
from plone.formwidget.contenttree.source import UUIDSourceBinder
from plone.uuid.interfaces import IAttributeUUID
from plone.uuid.interfaces import IUUID
from z3c.form import widget
from zope.interface import Interface, Invalid, invariant, implements
from zope.component.hooks import getSite
from zope.container.interfaces import IOrderedContainer
from zope.location.interfaces import ILocation
from zope import schema
from zope.schema.interfaces import IContextSourceBinder
from zope.schema.vocabulary import SimpleVocabulary, SimpleTerm
from collective.z3cform.colorpicker import colorpicker

from uu.formlibrary.measure.interfaces import MEASURE_DEFINITION_TYPE

from uu.chart import _ #MessageFactory for package


## globals for vocabulary and summarization/aggregate functions

F_MEAN = lambda l: float(sum(l))/len(l) if len(l) > 0 else float('nan')

def F_MEDIAN(l):
    """
    Return middle value of sorted sequence for an odd-sized
    list, or return the arithmetic mean of the two middle-values
    in an even-sized list.
    """
    odd = lambda v: bool(v%2)
    s, size = sorted(l), len(l)
    middle = size/2
    _slice = slice((middle - 1), (middle + 1))
    return s[middle] if odd(size) else F_MEAN(s[_slice])


AGGREGATE_FUNCTIONS = {
    'SUM': sum,
    'AVG': F_MEAN,
    'PRODUCT': lambda l: reduce(operator.mul, l),
    'MIN' : min,
    'MAX' : max,
    'MEDIAN': F_MEDIAN,
    'COUNT': len,
}

AGGREGATE_LABELS = [
    ('SUM', u'Sum'),
    ('AVG', u'Average'),
    ('PRODUCT', u'Product'),
    ('MIN', u'Minimum'),
    ('MAX', u'Maximum'),
    ('MEDIAN', u'Median'),
    ('COUNT', u'Count of occurrences'),
]

SUMMARIZATION_STRATEGIES = AGGREGATE_LABELS + [
    ('FIRST', u'Pick first found value'),
    ('LAST', u'Pick last found value'),
    ('IGNORE', u'Ignore more than one value, omit on encountered duplication'),
]

VOCAB_SUMMARIZATION = SimpleVocabulary(
    [SimpleTerm(v, title=title) for v, title in SUMMARIZATION_STRATEGIES]
)


FREQ_VOCAB = SimpleVocabulary(
    [SimpleTerm(v, title=title) for v, title in [
        ('monthly', u'Monthly'),
        ('weekly', u'Weekly'),
        ('yearly', u'Yearly'),
        ('quarterly', u'Quarterly'),
    ]]
)


def resolve_uid(uid):
    catalog = getSite().portal_catalog
    r = catalog.search({'UID': str(uid)})
    if not r:
        return None
    return r[0].getObject()


def provider_measure(context):
    """Given measure-provider for data sequence, get its bound measure"""
    # IMeasureSeriesProvider['measure'] field:
    measure_uid = getattr(context, 'measure', None)
    if measure_uid is None:
        return None
    return resolve_uid(measure_uid)


class MeasureGroupContentSourceBinder(object):
    """
    Source binder for listing items contained in measure group parent of
    a measure context, filtered by type.
    """
    
    implements(IContextSourceBinder)
    
    def __init__(self, portal_type=None):
        self.typename = str(portal_type)
    
    def __call__(self, context):
        measure = provider_measure(context)
        if measure is None:
            return UUIDSourceBinder(portal_type=self.typename)(context)
        group = measure.group()  # group (folder) containing measure def'n
        contained = group.contentValues()
        if self.typename:
            contained = filter(
                lambda o: o.portal_type == self.typename,
                contained,
                )
        terms = map(
            lambda o: SimpleTerm(IUUID(o), title=o.Title().decode('utf-8')),
            contained,
            )
        return SimpleVocabulary(terms)


class RWColorPickerWidget(colorpicker.ColorpickerWidget):
    """
    Color picker that is read-write and uses JS to keep
    the string value of 'Auto' for null/empty/non-specified
    color values.
    """
    readonly = False
    
    def getJS(self):
        orig = super(RWColorPickerWidget, self).getJS()
        lines = orig.split('\n')
        js_additional = """
            var htmlcolor = /^#?([a-f]|[A-F]|[0-9]){3}(([a-f]|[A-F]|[0-9]){3})?$/;
            var input = jQuery('#%s');
            if (!input[0].value) input.value = 'Auto';
            input.css('color', '#bbb');
            input.change(function(event) {
                if (!htmlcolor.test(this.value)) {
                    this.value = 'Auto';
                    input.css('color', '#bbb'); 
                    input.css('backgroundColor', 'white');
                }
            });
            """.replace('%s', self.id).strip()
        lines.insert(-1, js_additional);
        return '\n'.join(lines)


def ColorpickerFieldWidget(field, request):
    """
    Get color picker field widget, set readonly to false on 
    each constrcuted widget instance.  This allows removing 
    a color and setting an empty string as a value.
    """
    return widget.FieldWidget(field, RWColorPickerWidget(request))


## constants for use in package:

TIME_DATA_TYPE = 'uu.chart.data.timeseries'     ## portal types should
NAMED_DATA_TYPE = 'uu.chart.data.namedseries'   ## match FTIs
MEASURE_DATA_TYPE = 'uu.chart.data.measureseries'


## sorting data-point identities need collation/comparator function
def cmp_point_identities(a,b):
    """
    Given point identities a, b (may be string, number, date, etc),
    collation algorithm compares:
    
      (a) strings case-insensitively

      (b) dates and datetimes compared by normalizing date->datetime.
      
      (c) all other types use __cmp__(self, other) defaults from type.

    """
    dt = lambda d: datetime(*d.timetuple()[0:6]) #date|datetime -> datetime
    if isinstance(a, basestring) and isinstance(b, basestring):
        return cmp(a.upper(), b.upper())
    if isinstance(a, date) or isinstance(b, date):
        return cmp(dt(a), dt(b))
    return cmp(a,b)


class IChartProductLayer(Interface):
    """Marker interface for product layer"""


class IDataPoint(Interface):
    """Data point contains single value and optional note and URI"""
    
    value = schema.Float(
        title=_(u'Number value'),
        description=_(u'Decimal number value.'),
        default=0.0,
        )
    
    note = schema.Text(
        title=_(u'Note'),
        description=_(u'Note annotating the data value for this point.'),
        required=False,
        )
    
    uri = schema.BytesLine(
        title=_(u'URI'),
        description=_(u'URI/URL or identifier to source of data'),
        required=False,
        )
    
    def identity():
        """
        Return identity (such as a name, date, id) for the point unique
        to the series in which it is contained.
        """


class INamedBase(Interface):
    """Mix-in schema for name field"""
    
    name = schema.TextLine(
        title=_(u'Name'),
        description=_(u'Series-unique name or category for data point.'),
        required=True,
        )
    
    def identity():
        """return self.name"""


class IDateBase(Interface):
    """Mix-in schema with date field"""
    
    date = schema.Date(
        title=_(u'Date'),
        required=True,
        )
        
    def identity():
        """return self.date"""


class INamedDataPoint(INamedBase, IDataPoint):
    """Data point with a series-unique categorical name"""    


class ITimeSeriesDataPoint(IDateBase, IDataPoint):
    """Data point with a distinct date"""


#--- series and collection interfaces:


class IDataSeries(form.Schema):
    """Iterable of IDataPoint objects"""
    
    form.fieldset(
        'configuration',
        label=u"Configuration",
        fields=[
            'units',
            'goal',
            'range_min',
            'range_max',
            'display_precision',
            ],
        )
    
    title = schema.TextLine(
        title=_(u'Title'),
        description=_(u'Name of data series; may be displayed as a label.'),
        required=True,
        )
    
    units = schema.TextLine(
        title=_(u'Units'),
        description=_(u'Units of measure for the series.'),
        required=False,
        )
    
    goal = schema.Float(
        title=_(u'Goal'),
        description=_(u'Goal value as floating point / decimal number'),
        required=False,
        )
    
    range_min = schema.Float(
        title=_(u'Range minimum'),
        description=_(u'Minimum anticipated value of any data point '\
                      u'(optional).'),
        required=False,
        )
    
    range_max = schema.Float(
        title=_(u'Range maximum'),
        description=_(u'Maximum anticipated value of any data point '\
                      u'(optional).'),
        required=False,
        )
    
    display_precision = schema.Int(
        title=u'Digits after decimal point (display precision)?',
        description=u'When displaying a decimal value, how many places '\
                    u'beyond the decimal point should be displayed in '\
                    u'output?  Default: two digits after the decimal point.',
        default=1,
        )
    
    def __iter__():
        """
        Return iterable of date, number data point objects providing
        (at least) IDataPoint.
        """
    
    def __len__():
        """Return number of data points"""


class IDataCollection(Interface):
    """
    Collection of one or more (related) data series and associated metadata.
    Usually the logical component of a chart with multiple data series.
    """
    
    title = schema.TextLine(
        title=_(u'Title'),
        description=_(u'Data collection name or title; may be displayed '\
                      u'in legend.'),
        required=False,
        )
    
    description = schema.Text(
        title=_(u'Description'),
        description=_(u'Textual description of the data collection.'),
        required=False,
        )
    
    units = schema.TextLine(
        title=_(u'Units'),
        description=_(u'Common set of units of measure for the data '\
                      u'series in this collection.  If the units '\
                      u'for series are not shared, then define '\
                      u'respective units on the series themselves. '\
                      u'May be displayed as part of Y-axis label.'),
        required=False,
        )
    
    goal = schema.Float(
        title=_(u'Goal'),
        description=_(u'Common goal value as decimal number.  If each '\
                      u'series has different respective goals, edit '\
                      u'those goals on each series.'),
        required=False,
        )
    
    def series():
        """
        return a iterable of IDataSeries objects.
        """
    
    def identities():
        """
        Return a sequence of sorted point identities (names, dates, etc)
        for all points contained in all series.  These identities are 
        effectively faceted classifiers for points.
        """


class ITimeSeriesCollection(IDataCollection):
    """
    Time series interface for configured range of time for all data
    series contained.  Adds date range configuration to collection.
    """
    
    start = schema.Date(
        title=_(u'Start date'),
        required=False,
        )
    
    end = schema.Date(
        title=_(u'End date'),
        required=False,
        )
    
    frequency = schema.Choice(
        title=u'Chart frequency',
        vocabulary=FREQ_VOCAB,
        default='monthly',
        )
    
    @invariant
    def validate_start_end(obj):
        if not (obj.start is None or obj.end is None) and obj.start > obj.end:
            raise Invalid(_(u"Start date cannot be after end date."))


# -- presentation and content interfaces:

class IChartDisplay(form.Schema):
    """
    Display configuration for chart settings (as a whole).
    """
    
    form.fieldset(
        'display',
        label=u"Display settings",
        fields=['height',
                'width',
                'show_goal',
                'goal_color',
                'legend_location',
                'legend_placement',
                'x_label',
                'y_label',
                'chart_styles',
                ]
        )

    width = schema.Int(
        title=_(u'Width'),
        description=_(u'Display width of chart in pixels.'),
        default=600,
        )
    
    height = schema.Int(
        title=_(u'Height'),
        description=_(u'Display height of chart in pixels.'),
        default=300,
        )

    show_goal = schema.Bool(
        title=_(u'Show goal-line?'),
        description=_(u'If defined, show (constant horizontal) goal line?'),
        default=False,
        )
    
    form.widget(goal_color=ColorpickerFieldWidget)
    goal_color = schema.TextLine(
        title=_(u'Goal-line color'),
        description=_(u'If omitted, color will be selected from defaults.'),
        required=False,
        default=u'Auto',
        )
    
    chart_type = schema.Choice(
        title=_(u'Chart type'),
        description=_(u'Type of chart to display.'),
        vocabulary=SimpleVocabulary([
            SimpleTerm(value=u'line', title=u'Line chart'),
            SimpleTerm(value=u'bar', title=u'Bar chart'),
            ]),
        default=u'line',
        )
    
    legend_location = schema.Choice(
        title=_(u'Legend location'),
        description=_(u'Select a directional position for legend.'),
        vocabulary=SimpleVocabulary((
            SimpleTerm(value=None, token=str(None), title=u'Disabled'),
            SimpleTerm(value='nw',title=_(u'Top left')),
            SimpleTerm(value='n', title=_(u'Top')),
            SimpleTerm(value='ne', title=_(u'Top right')),
            SimpleTerm(value='e', title=_(u'Right')),
            SimpleTerm(value='se', title=_(u'Bottom right')),
            SimpleTerm(value='s', title=_(u'Bottom')), 
            SimpleTerm(value='sw', title=_(u'Bottom left')),
            SimpleTerm(value='w', title=_(u'Left')),
            )),
        required=False,
        default='e',  # right hand side
        )
    
    legend_placement = schema.Choice(
        title=_(u'Legend placement'),
        description=_(u'Where to place legend in relationship to the grid.'),
        vocabulary=SimpleVocabulary((
            SimpleTerm(value='outside', title=_(u'Outside grid')),
            SimpleTerm(value='inside', title=_(u'Inside grid')),
            )),
        required=True,
        default='outside',
        )
   
    x_label = schema.TextLine(
        title=_(u'X axis label'),
        default=u'',
        required=False,
        )

    y_label = schema.TextLine(
        title=_(u'Y axis label'),
        default=u'',
        required=False,
        )

    chart_styles = schema.Bytes(
        title=_(u'Chart styles'),
        description=_(u'CSS stylesheet rules for chart (optional).'),
        required=False,
        )


class ISeriesDisplay(form.Schema):
    """
    Common display settings for visualizing a series as either a bar
    or line chart.
    """
    
    form.widget(color=ColorpickerFieldWidget)
    color = schema.TextLine(
        title=_(u'Series color'),
        description=_(u'If omitted, color will be selected from defaults.'),
        required=False,
        default=u'Auto',
        )
    
    show_trend = schema.Bool(
        title=_(u'Show trend-line?'),
        description=_(u'Display a linear trend line?  If enabled, uses '\
                      u'configuration options specified.'),
        default=False,
        )
    
    trend_width = schema.Int(
        title=_(u'Trend-line width'),
        description=_(u'Line width of trend-line in pixel units.'),
        default=2,
        )
    
    form.widget(trend_color=ColorpickerFieldWidget)
    trend_color = schema.TextLine(
        title=_(u'Trend-line color'),
        description=_(u'If omitted, color will be selected from defaults.'),
        required=False,
        default=u'Auto',
        )


class ILineDisplay(form.Schema, ISeriesDisplay):
    """
    Mixin interface for display-line configuration metadata for series line.
    
    Note: while a series can have a specific goal value, only one
    goal per-chart is considered for goal-line display.  It is therefore up
    to implementation to choose reasonable aspects for display (or omission)
    of line/series specific goals.
    """
     
    form.fieldset(
        'display',
        label=u"Display settings",
        fields=[
            'color',
            'line_width',
            'marker_style',
            'marker_size',
            'marker_width',
            'marker_color',
            'show_trend',
            'trend_width',
            'trend_color',
            'break_lines',
            ],
        )
    
    line_width = schema.Int(
        title=_(u'Line width'),
        description=_(u'Width/thickness of line in pixel units.'),
        default=2,
        )
    
    marker_style = schema.Choice(
        title=_(u'Marker style'),
        description=_(u'Shape/type of the point-value marker.'),
        vocabulary=SimpleVocabulary([
            SimpleTerm(value=u'diamond', title=u'Diamond'),
            SimpleTerm(value=u'circle', title=u'Circle'),
            SimpleTerm(value=u'square', title=u'Square'),
            SimpleTerm(value=u'x', title=u'X'),
            SimpleTerm(value=u'plus', title=u'Plus sign'),
            SimpleTerm(value=u'dash', title=u'Dash'),
            SimpleTerm(value=u'filledDiamond', title=u'Filled diamond'),
            SimpleTerm(value=u'filledCircle', title=u'Filled circle'),
            SimpleTerm(value=u'filledSquare', title=u'Filled square'),
            ]),
        default=u'square',
        )
    
    marker_size = schema.Float(
        title=_(u'Marker size'),
        description=_(u'Size of the marker (diameter or circle, length of '\
                      u'edge of square, etc) in decimal pixels.'),
        required=False,
        default=9.0,
        )   
    
    marker_width = schema.Int(
        title=_(u'Marker line width'),
        description=_(u'Line width of marker in pixel units for '\
                      u'non-filled markers.'),
        required=False,
        default=2,
        )
    
    form.widget(marker_color=ColorpickerFieldWidget)
    marker_color = schema.TextLine(
        title=_(u'Marker color'),
        description=_(u'If omitted, color will be selected from defaults.'),
        required=False,
        default=u'Auto',
        )

    break_lines  = schema.Bool(
        title=u'Break lines?',
        description=u'When a value is missing for name or date on the '\
                    u'X axis, should the line be broken/discontinuous '\
                    u'such that no line runs through the empty/null '\
                    u'value?  This defaults to False, which means that '\
                    u'a line will run from adjacent values through the '\
                    u'missing value; if you do not want this, enable '\
                    u'this.',
        default=False,
        )

# --- content type interfaces: ---

class IBaseChart(form.Schema, ILocation, IAttributeUUID):
    """Base chart (content item) interface"""
    
    form.omitted('__name__')
    
    form.fieldset(
        'about',
        label=u"About",
        fields=['info'],
        )
    
    info = RichText(
        title=_(u'Informative notes'),
        description=_(u'This allows any rich text and may contain free-form '\
                      u'notes about this chart; displayed in report output.'),
        required=False,
        )

# -- timed series chart interfaces:

class ITimeSeriesChart(IBaseChart,
                       ITimeSeriesCollection,
                       IChartDisplay):
    """Chart content item; container for sequences"""
 
    auto_crop = schema.Bool(
        title=u'Auto-crop to completed data?',
        description=u'If data contains sequential null values (incomplete '\
                    u'or no data calculable) on the right-hand of a '\
                    u'time-series plot, should that right-hand side '\
                    u'be cropped to only show the latest meaningful '\
                    u'data?  The default is to crop automatically.',
        default=True,
        )

    def series():
        """
        return a iterable of IDataSeries objects for all contained
        series.  Points in each series should provide ITimeSeriesDataPoint.
        """


DATE_AXIS_LABEL_CHOICES = SimpleVocabulary(
    [
        SimpleTerm(value, title=title) for value, title in (
            ('locale', u'MM/DD/YYYY'),
            ('iso8601', u'YYYY-MM-DD'),
            ('name', u'Month name only'),
            ('name+year', u'Month name and year'),
            ('abbr', u'Month abbreviation'),
            ('abbr+year', u'Month abbreviation, with year'),
        )
    ]
)

class ITimeDataSequence(form.Schema, IDataSeries, ILineDisplay):
    """Content item interface for a data series stored as content"""
    
    input = schema.Text(
        title=_(u'Data input'),
        description=_(u'Comma-separated records, one per line '\
                      u'(date, numeric value, [note], [URL]). '\
                      u'Note and URL are optional. Date '\
                      u'should be in MM/DD/YYYY format.'),
        default=u'',
        required=False,
        )
    
    label_default = schema.Choice(
        title=_(u'Label default'),
        description=_(u'Default format for X-Axis labels.'),
        default='locale',
        vocabulary=DATE_AXIS_LABEL_CHOICES,
        )
    
    form.omitted('label_overrides')
    label_overrides = schema.Dict(
        key_type=schema.Date(),
        value_type=schema.BytesLine(),
        defaultFactory=PersistentDict,
        required=False,
        )
    
    form.omitted('data')
    data = schema.List(
        title=_(u'Data'),
        description=_(u'Data points for time series: date, value; values are '\
                      u'either whole/integer or decimal numbers.'),
        value_type=schema.Object(
            schema=ITimeSeriesDataPoint,
            ),
        readonly=True,
        )
    

# -- named series chart interfaces:

class INamedSeriesChart(IBaseChart, IDataCollection, IChartDisplay):
    """
    Named/categorical chart: usually a bar chart with x-axis containing
    categorical enumerated names/labels, and Y-axis representing values
    for that label.
    """
    
    chart_type = schema.Choice(
        title=_(u'Chart type'),
        description=_(u'Type of chart to display.'),
        vocabulary=SimpleVocabulary([
            SimpleTerm(value=u'bar', title=u'Bar chart'),
            SimpleTerm(value=u'stacked', title=u'Stacked bar chart'),
            ]),
        default=u'bar',
        )
    
    def series():
        """
        return a iterable of IDataSeries objects for all contained
        series.  Points in each series should provide INamedSeriesDataPoint.
        """

class INamedDataSequence(form.Schema, IDataSeries, ISeriesDisplay):
    """Named category seqeuence with embedded data stored as content"""
    
    form.fieldset(
        'display',
        label=u"Display settings",
        fields=[
            'color',
            'show_trend',
            'trend_width',
            'trend_color',
            ],
        )
    
    input = schema.Text(
        title=_(u'Data input'),
        description=_(u'Comma-separated records, one per line '\
                      u'(name, numeric value, [note], [URL]). '\
                      u'Note and URL are optional.'),
        default=u'',
        required=False,
        )
    
    # data field to store CSV source:
    form.omitted('data')
    data = schema.List(
        title=_(u'Data'),
        description=_(u'Data points for series: name, value; values are '\
                      u'either whole/integer or decimal numbers.'),
        value_type=schema.Object(
            schema=INamedDataPoint,
            ),
        readonly=True,
        )


# report container/folder interfaces:

class IDataReport(form.Schema, IOrderedContainer, IAttributeUUID):
    """
    Ordered container/folder of contained charts providing ITimeSeriesChart.
    """
    
    title = schema.TextLine(
        title=_(u'Title'),
        description=_(u'Report title; may be displayed in output.'),
        required=False,
        )
    
    description = schema.Text(
        title=_(u'Description'),
        description=_(u'Textual description of the report.'),
        required=False,
        )


class IMeasureSeriesProvider(form.Schema, IDataSeries, ILineDisplay):
    
    form.widget(measure=ContentTreeFieldWidget)
    measure = schema.Choice(
        title=u'Bound measure',
        description=u'Measure definition that defines a function to apply '\
                    u'to a dataset of forms to obtain a computed value for '\
                    u'each as a data-point.',
        source=UUIDSourceBinder(
            portal_type=MEASURE_DEFINITION_TYPE,
            ),
        )
    
    dataset = schema.Choice(
        title=u'Data set (collection)',
        description=u'Select a collection that enumerates which forms are '
                    u'considered part of the data set to query for data. '\
                    u'You must select a collection within the same measure '\
                    u'group in which the bound measure definition is '\
                    u'contained.',                    
        source=MeasureGroupContentSourceBinder(
            portal_type='Topic',
            ),
        required=False,
        )
    
    summarization_strategy = schema.Choice(
        title=u'Summarization strategy',
        description=u'How should data be summarized into a single value '\
                    u'when multiple competing values for date or name '\
                    u'are found in the data stream provided by the measure '\
                    u'and data set?  For example you may average or sum '\
                    u'the multiple values, take the first or last, '\
                    u'or you may choose to treat such competing values as '\
                    u'a conflict, and omit any value on duplication.',
        vocabulary=VOCAB_SUMMARIZATION,
        default='AVG',
        )
    
    form.omitted('data')
    data = schema.List(
        title=_(u'Data'),
        description=_(u'Data points computed from bound dataset, measure '\
                      u'selected.  Should return an empty list if any '\
                      u'bindings are missing. '\
                      u'Whether the data point key/identity type is a date '\
                      u'or a name will depend on the type of chart '\
                      u'containing this data provider.'),
        value_type=schema.Object(
            schema=IDataPoint,
            ),
        readonly=True,
        )

