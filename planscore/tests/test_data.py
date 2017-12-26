import unittest, unittest.mock, fractions
from .. import data

class TestData (unittest.TestCase):

    def test_Storage(self):
        ''' Storage.from_event() creates the right properties.
        '''
        s3 = unittest.mock.Mock()
        storage = data.Storage.from_event(dict(bucket='bucket', prefix='XX'), s3)
        self.assertEqual(storage.s3, s3)
        self.assertEqual(storage.bucket, 'bucket')
        self.assertEqual(storage.prefix, 'XX')

    def test_upload_storage(self):
        ''' Past and future data.Upload instances are readable
        '''
        upload1 = data.Upload.from_json('{"id": "ID", "key": "KEY"}')
        self.assertEqual(upload1.id, 'ID')
        self.assertEqual(upload1.key, 'KEY')
        self.assertEqual(upload1.districts, [])

        upload2 = data.Upload.from_json('{"id": "ID", "key": "KEY", "districts": ["yo"]}')
        self.assertEqual(upload2.id, 'ID')
        self.assertEqual(upload2.key, 'KEY')
        self.assertEqual(upload2.districts, ['yo'])

        upload3 = data.Upload.from_json('{"id": "ID", "key": "KEY", "districts": ["yo"], "summary": ["oi"]}')
        self.assertEqual(upload3.id, 'ID')
        self.assertEqual(upload3.key, 'KEY')
        self.assertEqual(upload3.districts, ['yo'])
        self.assertEqual(upload3.summary, ['oi'])

        upload4 = data.Upload.from_json('{"id": "ID", "key": "KEY", "progress": [1, 2]}')
        self.assertEqual(upload4.id, 'ID')
        self.assertEqual(upload4.key, 'KEY')
        self.assertEqual(upload4.progress, fractions.Fraction(1, 2))

    def test_upload_json(self):
        ''' data.Upload instances can be converted to and from JSON
        '''
        upload1 = data.Upload(id='ID', key='uploads/ID/upload/whatever.json')
        upload2 = data.Upload.from_json(upload1.to_json())

        self.assertEqual(upload2.id, upload1.id)
        self.assertEqual(upload2.key, upload1.key)
        self.assertEqual(upload2.districts, upload1.districts)
        self.assertEqual(upload2.summary, upload1.summary)
    
        upload3 = data.Upload(id='ID', key='uploads/ID/upload/whatever.json', districts=['yo', 'yo', 'yo'])
        upload4 = data.Upload.from_json(upload3.to_json())

        self.assertEqual(upload4.id, upload3.id)
        self.assertEqual(upload4.key, upload3.key)
        self.assertEqual(upload4.districts, upload3.districts)
        self.assertEqual(upload4.summary, upload3.summary)
    
        upload5 = data.Upload(id='ID', key='uploads/ID/upload/whatever.json',
            districts=['yo', 'yo', 'yo'], summary=['oi', 'oi', 'oi'])
        upload6 = data.Upload.from_json(upload5.to_json())

        self.assertEqual(upload6.id, upload5.id)
        self.assertEqual(upload6.key, upload5.key)
        self.assertEqual(upload6.districts, upload5.districts)
        self.assertEqual(upload6.summary, upload5.summary)
    
        upload7 = data.Upload(id='ID', key='uploads/ID/upload/whatever.json',
            progress=fractions.Fraction(1, 2))
        upload8 = data.Upload.from_json(upload7.to_json())

        self.assertEqual(upload8.id, upload7.id)
        self.assertEqual(upload8.key, upload7.key)
        self.assertEqual(upload8.progress, upload7.progress)
    
    def test_upload_plaintext(self):
        ''' data.Upload instances can be converted to plaintext
        '''
        upload1 = data.Upload(id='ID', key='uploads/ID/upload/whatever.json',
            districts=[
                { "totals": { "Democratic Votes": 100, "Population 2015": 200, "Republican Votes": 300 } },
                { "totals": { "Democratic Votes": 400, "Population 2015": 500, "Republican Votes": 600 } },
                { "totals": { "Democratic Votes": 700, "Population 2015": 800, "Republican Votes": 900 } }
              ])
        
        plaintext1 = upload1.to_plaintext()
        head, row1, row2, row3, tail = plaintext1.split('\r\n', 4)
        
        self.assertEqual(head, 'District\tDemocratic Votes\tRepublican Votes\tPopulation 2015')
        self.assertEqual(row1, '1\t100\t300\t200')
        self.assertEqual(row2, '2\t400\t600\t500')
        self.assertEqual(row3, '3\t700\t900\t800')
        self.assertEqual(tail, '')

        upload2 = data.Upload(id='ID', key='uploads/ID/upload/whatever.json',
            districts=[ { "garbage": True } ])
        
        plaintext2 = upload2.to_plaintext()
        self.assertEqual(plaintext2, "Error: 'totals'\n")

    def test_upload_index_key(self):
        ''' data.Upload.index_key() correctly munges Upload.key
        '''
        upload = data.Upload(id='ID', key='uploads/ID/upload/whatever.json')
        self.assertEqual(upload.index_key(), 'uploads/ID/index.json')
    
    def test_upload_plaintext_key(self):
        ''' data.Upload.plaintext_key() correctly munges Upload.key
        '''
        upload = data.Upload(id='ID', key='uploads/ID/upload/whatever.json')
        self.assertEqual(upload.plaintext_key(), 'uploads/ID/index.txt')
    
    def test_upload_geometry_key(self):
        ''' data.Upload.geometry_key() correctly munges Upload.key
        '''
        upload = data.Upload(id='ID', key='uploads/ID/upload/whatever.json')
        self.assertEqual(upload.geometry_key(), 'uploads/ID/geometry.json')
    
    def test_upload_district_key(self):
        ''' data.Upload.district_key() correctly munges Upload.key
        '''
        upload = data.Upload(id='ID', key='uploads/ID/upload/whatever.json')
        self.assertEqual(upload.district_key(999), 'uploads/ID/districts/999.json')
    
    def test_upload_clone(self):
        ''' data.Upload.clone() returns a copy with the right properties
        '''
        districts1, districts2 = unittest.mock.Mock(), unittest.mock.Mock()
        summary1, summary2 = unittest.mock.Mock(), unittest.mock.Mock()
        progress1, progress2 = unittest.mock.Mock(), unittest.mock.Mock()
        input = data.Upload(id='ID', key='whatever.json',
            districts=districts1, summary=summary1, progress=progress1)

        self.assertIs(input.districts, districts1)
        self.assertIs(input.summary, summary1)
        self.assertIs(input.progress, progress1)

        output1 = input.clone(districts=districts2, summary=summary2)
        self.assertEqual(output1.id, input.id)
        self.assertEqual(output1.key, input.key)
        self.assertIs(output1.districts, districts2)
        self.assertIs(output1.summary, summary2)

        output2 = input.clone()
        self.assertEqual(output2.id, input.id)
        self.assertEqual(output2.key, input.key)
        self.assertIs(output2.districts, input.districts)
        self.assertIs(output2.summary, input.summary)
        self.assertIs(output2.progress, input.progress)

        output3 = input.clone(districts=None, summary=None)
        self.assertEqual(output3.id, input.id)
        self.assertEqual(output3.key, input.key)
        self.assertIs(output3.districts, input.districts)
        self.assertIs(output3.summary, input.summary)
        self.assertIs(output3.progress, input.progress)

        output4 = input.clone(progress=progress2)
        self.assertEqual(output4.id, input.id)
        self.assertEqual(output4.key, input.key)
        self.assertIs(output4.progress, progress2)
