import json, csv, io, time, enum
from . import constants

UPLOAD_PREFIX = 'uploads/{id}/upload/'
UPLOAD_INDEX_KEY = 'uploads/{id}/index.json'
UPLOAD_PLAINTEXT_KEY = 'uploads/{id}/index.txt'
UPLOAD_GEOMETRY_KEY = 'uploads/{id}/geometry.json'
UPLOAD_DISTRICTS_KEY = 'uploads/{id}/districts/{index}.json'
UPLOAD_GEOMETRIES_KEY = 'uploads/{id}/geometries/{index}.wkt'
UPLOAD_TILE_INDEX_KEY = 'uploads/{id}/tiles.json'
UPLOAD_TILES_KEY = 'uploads/{id}/tiles/{zxy}.json'

class State (enum.Enum):
    XX = 'XX'
    MD = 'MD'; NC = 'NC'; PA = 'PA'; WI = 'WI'

class House (enum.Enum):
    ushouse = 'ushouse'; statesenate = 'statesenate'; statehouse = 'statehouse'

class Storage:
    ''' Wrapper for S3-related details.
    '''
    def __init__(self, s3, bucket, prefix):
        self.s3 = s3
        self.bucket = bucket
        self.prefix = prefix
    
    def to_event(self):
        return dict(bucket=self.bucket, prefix=self.prefix)
    
    @staticmethod
    def from_event(event, s3):
        bucket = event['bucket']
        prefix = event.get('prefix')
        return Storage(s3, bucket, prefix)

class Progress:
    ''' Fraction-like value representing number of completed districts.
    
        Not using fractions.Fraction because it reduces to lowest terms.
    '''
    def __init__(self, completed, expected):
        self.completed = completed
        self.expected = expected
    
    def to_list(self):
        return [self.completed, self.expected]
    
    def to_percentage(self):
        try:
            return '{:.0f}%'.format(100 * self.completed / self.expected)
        except ZeroDivisionError:
            return '???%'
    
    def is_complete(self):
        return bool(self.completed >= self.expected)
    
    def __eq__(self, other):
        return (self.completed / self.expected) == (other.completed / other.expected)

class Model:

    def __init__(self, state:State, house:House, seats:int, key_prefix:str):
        self.state = state
        self.house = house
        self.seats = seats
        self.key_prefix = key_prefix
    
    def to_dict(self):
        return dict(
            state = self.state.value,
            house = self.house.value,
            seats = self.seats,
            key_prefix = self.key_prefix,
            )
    
    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)
    
    @staticmethod
    def from_dict(data):
        return Model(
            state = State[data['state']],
            house = House[data['house']],
            seats = int(data['seats']),
            key_prefix = str(data['key_prefix'])
            )
    
    @staticmethod
    def from_json(body):
        return Model.from_dict(json.loads(body))

class Upload:

    def __init__(self, id, key, model:Model=None, districts=None, summary=None,
            progress=None, start_time=None, message=None, **ignored):
        self.id = id
        self.key = key
        self.model = model
        self.districts = districts or []
        self.summary = summary or {}
        self.progress = progress
        self.start_time = start_time or time.time()
        self.message = message
    
    def is_overdue(self):
        return bool(time.time() > (self.start_time + constants.UPLOAD_TIME_LIMIT))
    
    def index_key(self):
        return UPLOAD_INDEX_KEY.format(id=self.id)
    
    def plaintext_key(self):
        return UPLOAD_PLAINTEXT_KEY.format(id=self.id)
    
    def geometry_key(self):
        return UPLOAD_GEOMETRY_KEY.format(id=self.id)
    
    def district_key(self, index):
        return UPLOAD_DISTRICTS_KEY.format(id=self.id, index=index)
    
    def to_plaintext(self):
        ''' Export district totals to a tab-delimited plaintext file
        '''
        sorting_hints = dict({k: i for (i, k) in enumerate((
            'District', 'Democratic Votes', 'Democratic Votes SD',
            'Republican Votes', 'Republican Votes, SD', 'Population 2015',
            'US President 2016 - DEM', 'US President 2016 - REP',
            'US Senate 2016 - DEM', 'US Senate 2016 - REP'))})
        
        try:
            column_names = sorted(self.districts[0]['totals'].keys(),
                key=lambda k: (sorting_hints.get(k, 999), k))
            
            column_names.extend(self.districts[0]['compactness'].keys())
        
            out = io.StringIO()
            rows = csv.DictWriter(out, ['District'] + column_names, dialect='excel-tab')
            rows.writeheader()
            for (index, district) in enumerate(self.districts):
                totals, compactness = district['totals'], district['compactness']
                rows.writerow(dict(District=index+1, **dict(totals, **compactness)))
        
        except Exception as e:
            return f'Error: {e}\n'

        else:
            return out.getvalue()
    
    def to_dict(self):
        progress = self.progress.to_list() if (self.progress is not None) else None

        return dict(
            id = self.id,
            key = self.key,
            model = (self.model.to_dict() if self.model else None),
            districts = self.districts,
            summary = self.summary,
            progress = progress,
            start_time = self.start_time,
            message = self.message,
            )
    
    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)
    
    def clone(self, model=None, districts=None, summary=None, progress=None,
        start_time=None, message=None):
        return Upload(self.id, self.key,
            model = model or self.model,
            districts = districts or self.districts,
            summary = summary or self.summary,
            progress = progress if (progress is not None) else self.progress,
            start_time = start_time or self.start_time,
            message = message or self.message,
            )
    
    @staticmethod
    def from_dict(data):
        progress = Progress(*data['progress']) if data.get('progress') else None
        model = Model.from_dict(data['model']) if data.get('model') else None
    
        return Upload(
            id = data['id'], 
            key = data['key'],
            model = model,
            districts = data.get('districts'),
            summary = data.get('summary'),
            progress = progress,
            start_time = data.get('start_time'),
            message = data.get('message'),
            )
    
    @staticmethod
    def from_json(body):
        return Upload.from_dict(json.loads(body))

# Active version of each state model

MODELS = [
    Model(State.XX, House.statehouse,    2, 'data/XX/003'),
    Model(State.MD, House.ushouse,       8, 'data/MD/001-ushouse-open'),
    Model(State.NC, House.ushouse,      13, 'data/NC/004-ushouse'),
    Model(State.NC, House.statesenate,  50, 'data/NC/004-ncsenate'),
    Model(State.NC, House.statehouse,  120, 'data/NC/004-nchouse'),
    Model(State.PA, House.ushouse,      18, 'data/PA/007-statehouse-open'), # 6b2ccb8
    Model(State.PA, House.statesenate,  50, 'data/PA/006-statesenate-multizoom'), # 25d464159
    Model(State.PA, House.statehouse,  203, 'data/WI/006-statehouse-multizoom'), # 25d464159
    Model(State.WI, House.ushouse,       8, 'data/WI/002-ushouse'),
    Model(State.WI, House.statesenate,  33, 'data/WI/002-statesenate'),
    Model(State.WI, House.statehouse,   99, 'data/WI/003-stateassembly-open'), # a073026
    ]