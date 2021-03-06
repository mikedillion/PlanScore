''' Functions used for scoring district symmetry.

When all districts are added up and present on S3, performs complete scoring
of district plan and uploads summary JSON file.
'''
import io, os, gzip, posixpath, json, statistics, copy, time, itertools
from osgeo import ogr
import boto3, botocore.exceptions
from . import data, constants

ogr.UseExceptions()

FIELD_NAMES = (
    # Toy fields
    'Voters', 'Blue Votes', 'Red Votes',
    'Population', 'Voting-Age Population', 'Black Voting-Age Population',
    'US Senate Rep Votes', 'US Senate Dem Votes', 'US House Rep Votes', 'US House Dem Votes',
    'SLDU Rep Votes', 'SLDU Dem Votes', 'SLDL Rep Votes', 'SLDL Dem Votes',

    # Real fields
    'Democratic Votes', 'Republican Votes',
    
    # ACS 2015 fields
    'Black Population 2015', 'Black Population 2015, Error',
    'Hispanic Population 2015', 'Hispanic Population 2015, Error',
    'Population 2015', 'Population 2015, Error',
    'Voting-Age Population 2015', 'Voting-Age Population 2015, Error',
    
    # ACS 2016 fields
    'Black Population 2016', 'Black Population 2016, Error',
    'Hispanic Population 2016', 'Hispanic Population 2016, Error',
    'Population 2016', 'Population 2016, Error',
    'Voting-Age Population 2016', 'Voting-Age Population 2016, Error',
    'Education Population 2016', 'Education Population 2016, Error',
    'High School or GED 2016', 'High School or GED 2016, Error',
    'Households 2016', 'Households 2016, Error',
    'Household Income 2016', 'Household Income 2016, Error',
    
    # CVAP 2015 fields
    'Citizen Voting-Age Population 2015',
    'Citizen Voting-Age Population 2015, Error',
    'Black Citizen Voting-Age Population 2015',
    'Black Citizen Voting-Age Population 2015, Error',
    'Hispanic Citizen Voting-Age Population 2015',
    'Hispanic Citizen Voting-Age Population 2015, Error',
    
    # Census 2010 fields
    'Population 2010',
    
    # Extra fields
    'US President 2016 - DEM', 'US President 2016 - REP',
    'US Senate 2016 - DEM', 'US Senate 2016 - REP'
    )

# Fields for simulated election vote totals
FIELD_NAMES += tuple([f'REP{sim:03d}' for sim in range(1000)])
FIELD_NAMES += tuple([f'DEM{sim:03d}' for sim in range(1000)])

def swing_vote(red_districts, blue_districts, amount):
    ''' Swing the vote by a percentage, positive toward blue.
    '''
    if amount == 0:
        return list(red_districts), list(blue_districts)
    
    districts = [(R, B, R + B) for (R, B) in zip(red_districts, blue_districts)]
    swung_reds = [((R/T - amount) * T) for (R, B, T) in districts if T > 0]
    swung_blues = [((B/T + amount) * T) for (R, B, T) in districts if T > 0]
    
    return swung_reds, swung_blues

def calculate_EG(red_districts, blue_districts, vote_swing=0):
    ''' Convert two lists of district vote counts into an EG score.
    
        By convention, result is positive for blue and negative for red.
    '''
    election_votes, wasted_red, wasted_blue, red_wins, blue_wins = 0, 0, 0, 0, 0
    red_districts, blue_districts = swing_vote(red_districts, blue_districts, vote_swing)
    
    # Calculate Efficiency Gap using swung vote
    for (red_votes, blue_votes) in zip(red_districts, blue_districts):
        district_votes = red_votes + blue_votes
        election_votes += district_votes
        win_threshold = district_votes / 2
        
        if red_votes > blue_votes:
            red_wins += 1
            wasted_red += red_votes - win_threshold # surplus
            wasted_blue += blue_votes # loser
        elif blue_votes > red_votes:
            blue_wins += 1
            wasted_blue += blue_votes - win_threshold # surplus
            wasted_red += red_votes # loser
        else:
            pass # raise ValueError('Unlikely 50/50 split')

    # Return an efficiency gap
    if election_votes == 0:
        return
    
    return (wasted_red - wasted_blue) / election_votes

def calculate_MMD(red_districts, blue_districts):
    ''' Convert two lists of district vote counts into a Mean-Median score.
    
        By convention, result is positive for blue and negative for red.
    
        Vote swing does not seem to affect Mean-Median, so leave it off.
    '''
    shares = sorted([R/(R + B) for (R, B) in zip(red_districts, blue_districts)])
    median = shares[len(shares)//2]
    mean = statistics.mean(shares)
    
    return mean - median

def calculate_PB(red_districts, blue_districts):
    ''' Convert two lists of district vote counts into a Partisan Bias score.
    
        By convention, result is positive for blue and negative for red.
    '''
    red_total, blue_total = sum(red_districts), sum(blue_districts)
    blue_margin = (blue_total - red_total) / (blue_total + red_total)
    
    reds_5050, blues_5050 = swing_vote(red_districts, blue_districts, -blue_margin/2)
    blue_seats = len([True for (R, B) in zip(reds_5050, blues_5050) if R < B])
    blue_seatshare = blue_seats / len(blues_5050)
    blue_voteshare = blue_total / (blue_total + red_total)
    
    return blue_seatshare - blue_voteshare

def calculate_bias(upload):
    ''' Calculate partisan metrics for districts with plain vote counts.
    '''
    summary_dict, gaps = {}, {
        'Red/Blue': ('Red Votes', 'Blue Votes'),
        'US House': ('US House Rep Votes', 'US House Dem Votes'),
        'SLDU': ('SLDU Rep Votes', 'SLDU Dem Votes'),
        'SLDL': ('SLDL Rep Votes', 'SLDL Dem Votes'),
        }
    
    first_totals = upload.districts[0]['totals']

    for (prefix, (red_field, blue_field)) in gaps.items():
        if red_field not in first_totals or blue_field not in first_totals:
            continue
    
        red_districts = [d['totals'].get(red_field) or 0 for d in upload.districts]
        blue_districts = [d['totals'].get(blue_field) or 0 for d in upload.districts]

        if prefix == 'Red/Blue':
            summary_dict['Mean-Median'] = calculate_MMD(red_districts, blue_districts)
            summary_dict['Partisan Bias'] = calculate_PB(red_districts, blue_districts)
            summary_dict['Efficiency Gap'] = calculate_EG(red_districts, blue_districts)

            # Calculate -5 to +5 point swings
            swings = itertools.product([1, 2, 3, 4, 5], [(.01, 'Blue'), (-.01, 'Red')])
            for (points, (swing, party)) in swings:
                gap = calculate_EG(red_districts, blue_districts, swing * points)
                summary_dict[f'Efficiency Gap +{points:.0f} {party}'] = gap
        else:
            summary_dict[f'{prefix} Mean-Median'] = calculate_MMD(red_districts, blue_districts)
            summary_dict[f'{prefix} Partisan Bias'] = calculate_PB(red_districts, blue_districts)
            summary_dict[f'{prefix} Efficiency Gap'] = calculate_EG(red_districts, blue_districts)

            # Calculate -5 to +5 point swings
            swings = itertools.product([1, 2, 3, 4, 5], [(.01, 'Dem'), (-.01, 'Rep')])
            for (points, (swing, party)) in swings:
                gap = calculate_EG(red_districts, blue_districts, swing * points)
                summary_dict[f'{prefix} Efficiency Gap +{points:.0f} {party}'] = gap
    
    return upload.clone(summary=summary_dict)

def calculate_biases(upload):
    ''' Calculate partisan metrics for districts with multiple simulations.
    '''
    MMDs, PBs = list(), list()
    EGs = {swing: list() for swing in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5)}
    summary_dict, copied_districts = dict(), copy.deepcopy(upload.districts)
    first_totals = copied_districts[0]['totals']
    
    if f'REP000' not in first_totals or f'DEM000' not in first_totals:
        return upload.clone()
    
    # Prepare place for simulation vote totals in each district
    all_red_districts = [list() for d in copied_districts]
    all_blue_districts = [list() for d in copied_districts]

    # Iterate over all simulations, tracking EG and vote totals
    for sim in range(1000):
        if f'REP{sim:03d}' not in first_totals or f'DEM{sim:03d}' not in first_totals:
            continue
        
        sim_red_districts, sim_blue_districts = list(), list()

        for (i, district) in enumerate(copied_districts):
            red_votes = district['totals'].pop(f'REP{sim:03d}')
            blue_votes = district['totals'].pop(f'DEM{sim:03d}')
            sim_red_districts.append(red_votes)
            sim_blue_districts.append(blue_votes)
            all_red_districts[i].append(red_votes)
            all_blue_districts[i].append(blue_votes)
    
        MMDs.append(calculate_MMD(sim_red_districts, sim_blue_districts))
        PBs.append(calculate_PB(sim_red_districts, sim_blue_districts))
        
        for swing in EGs:
            EGs[swing].append(calculate_EG(sim_red_districts, sim_blue_districts, swing/100))
    
    # Finalize per-district vote totals and confidence intervals
    for (i, district) in enumerate(copied_districts):
        red_votes, blue_votes = all_red_districts[i], all_blue_districts[i]
        district['totals'].update({
            'Democratic Votes': round(statistics.mean(blue_votes), constants.ROUND_COUNT),
            'Republican Votes': round(statistics.mean(red_votes), constants.ROUND_COUNT),
            'Democratic Votes SD': round(statistics.stdev(blue_votes), constants.ROUND_COUNT),
            'Republican Votes SD': round(statistics.stdev(red_votes), constants.ROUND_COUNT)
            })

    summary_dict['Mean-Median'] = statistics.mean(MMDs)
    summary_dict['Mean-Median SD'] = statistics.stdev(MMDs)
    summary_dict['Partisan Bias'] = statistics.mean(PBs)
    summary_dict['Partisan Bias SD'] = statistics.stdev(PBs)
    summary_dict['Efficiency Gap'] = statistics.mean(EGs[0])
    summary_dict['Efficiency Gap SD'] = statistics.stdev(EGs[0])
    
    for swing in (1, 2, 3, 4, 5):
        summary_dict[f'Efficiency Gap +{swing} Dem'] = statistics.mean(EGs[swing])
        summary_dict[f'Efficiency Gap +{swing} Rep'] = statistics.mean(EGs[-swing])
        summary_dict[f'Efficiency Gap +{swing} Dem SD'] = statistics.stdev(EGs[swing])
        summary_dict[f'Efficiency Gap +{swing} Rep SD'] = statistics.stdev(EGs[-swing])
    
    rounded_summary_dict = {k: round(v, constants.ROUND_FLOAT) for (k, v) in summary_dict.items()}
    return upload.clone(districts=copied_districts, summary=rounded_summary_dict)
