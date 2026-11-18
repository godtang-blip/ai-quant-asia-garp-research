"""Synthetic financial statement fixtures with explicit comparative denominators."""
from bs4 import BeautifulSoup

from src.filing_tables import check_table_observation, extract_html_tables


def _parse(html):
    return extract_html_tables(BeautifulSoup(html, 'html.parser'))


def _proposal(cell, **changes):
    proposal = {key: getattr(cell, key) for key in
                ('cell_id', 'metric_label', 'value_text', 'currency', 'unit', 'period_start', 'period_end')}
    proposal['quote'] = cell.row_text
    proposal.update(changes)
    return proposal


def test_static_comparative_columns_keep_source_coordinates_and_explicit_scale():
    passage, = _parse('''
        <h2>Consolidated balance sheets</h2>
        <p>Amounts in millions of Taiwan dollars</p>
        <table><thead><tr><th rowspan="2">Metric</th><th colspan="2">As of</th></tr>
        <tr><th>December 31, 2025</th><th>December 31, 2024</th></tr></thead>
        <tbody><tr><th>Total assets<sup>3</sup></th><td>123,456</td><td>112,456</td></tr></tbody></table>
    ''')
    current, prior = passage.cells
    assert (current.location, prior.location) == (
        'HTML table 1, row 3, cell 2', 'HTML table 1, row 3, cell 3')
    assert current.metric_label == 'Total assets'
    assert current.column_header == 'As of | December 31, 2025'
    assert (current.period_end, prior.period_end) == ('2025-12-31', '2024-12-31')
    assert current.period_start == '' and current.period_kind == 'POINT_IN_TIME'
    assert (current.currency, current.unit, current.unit_text) == ('TWD', 'millions', 'millions of Taiwan dollars')
    result = check_table_observation(_proposal(current), passage)
    assert result['verification_status'] == 'SOURCE_TEXT_MATCH'
    assert result['filing_verified'] is False
    assert result['decimal_value_as_reported'] == '123456'
    assert result['supporting_text'] == 'Total assets | 123,456 | 112,456'
    assert check_table_observation(_proposal(current, value_text=prior.value_text), passage) is None
    wrong_period = check_table_observation(_proposal(current, period_end=prior.period_end), passage)
    assert wrong_period['verification_status'] == 'PROVISIONAL_CONTEXT_UNRESOLVED'
    assert wrong_period['period_end'] == current.period_end
    assert wrong_period['uncertainty_reasons'] == ['MODEL_PERIOD_END_DOES_NOT_MATCH_SOURCE']


def test_duration_does_not_invent_start_or_borrow_scale_across_tables():
    second, first = _parse('''
        <p>Amounts in HKD millions</p>
        <table><tr><th>Metric</th><th>Year ended December 31, 2025</th></tr>
        <tr><td>Operating loss</td><td>(938)</td></tr></table>
        <h2>Consolidated statement of cash flows</h2>
        <table><tr><th>Metric</th><th>Year ended December 31, 2025</th></tr>
        <tr><td>Cash from investing</td><td>401</td></tr></table>
    ''')
    operating_loss, = first.cells
    assert (operating_loss.currency, operating_loss.period_end) == ('HKD', '2025-12-31')
    assert operating_loss.period_start == ''
    result = check_table_observation(_proposal(operating_loss, period_start='2025-01-01'), first)
    assert result['decimal_value_as_reported'] == '-938'
    assert result['verification_status'] == 'PROVISIONAL_CONTEXT_UNRESOLVED'
    assert result['uncertainty_reasons'] == ['REPORTING_PERIOD_UNRESOLVED',
                                            'MODEL_PERIOD_START_DOES_NOT_MATCH_SOURCE']
    cash, = second.cells
    assert not cash.currency and not cash.unit


IX_RESOURCES = '''
<ix:header><ix:resources>
    <xbrli:context id="current">
      <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <xbrli:context id="prior">
      <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <xbrli:unit id="tw"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
</ix:resources></ix:header>
'''


def test_tagged_context_verifies_same_printed_comparative_values_independently():
    passage, = _parse(IX_RESOURCES + '''
        <p>(TWD millions)</p>
        <table><tr><th>Metric</th><th>2025</th><th>2024</th></tr>
        <tr><td>Revenue</td>
        <td><ix:nonfraction contextRef="current" unitRef="tw" name="ifrs:Revenue" scale="6">123</ix:nonfraction></td>
        <td><ix:nonfraction contextRef="prior" unitRef="tw" name="ifrs:Revenue" scale="6">123</ix:nonfraction></td></tr></table>
    ''')
    current, prior = passage.cells
    assert current.value_text == prior.value_text
    for cell, year in ((current, '2025'), (prior, '2024')):
        result = check_table_observation(_proposal(cell), passage)
        assert result['verification_status'] == 'SOURCE_TEXT_MATCH'
        assert result['period_start'] == year + '-01-01'
        assert result['period_end'] == year + '-12-31'
        assert result['source_entity_identifier'] == '0001234567'
        assert result['source_xbrl_concept'] == 'ifrs:Revenue'
        assert result['unit'] == 'millions'
    assert current.cell_id != prior.cell_id
    assert check_table_observation(_proposal(current, cell_id='missing'), passage) is None
    swapped = check_table_observation(_proposal(current, cell_id=prior.cell_id), passage)
    assert swapped['uncertainty_reasons'] == [
        'MODEL_PERIOD_START_DOES_NOT_MATCH_SOURCE', 'MODEL_PERIOD_END_DOES_NOT_MATCH_SOURCE']


def test_tagged_context_conflicts_with_visible_dates_and_currencies():
    passage, = _parse(IX_RESOURCES + '''
        <p>HKD thousands</p>
        <table><tr><th>Metric</th><th>Year ended December 31, 2024</th></tr>
        <tr><td>Revenue</td>
        <td><ix:nonfraction contextRef="current" unitRef="tw" scale="6">123</ix:nonfraction></td></tr></table>
    ''')
    cell, = passage.cells
    result = check_table_observation(_proposal(cell), passage)
    assert result['verification_status'] == 'PROVISIONAL_CONTEXT_UNRESOLVED'
    assert set(result['uncertainty_reasons']) == {
        'PRESENTATION_CURRENCY_CONFLICTS_WITH_INLINE_XBRL',
        'PRESENTATION_SCALE_CONFLICTS_WITH_INLINE_XBRL',
        'COLUMN_PERIOD_CONFLICTS_WITH_INLINE_XBRL',
    }


def test_other_column_units_are_not_borrowed_and_split_sign_is_provisional():
    passage, = _parse('''
      <h2>Consolidated balance sheets</h2>
      <table>
        <tr><th>Metric</th><th></th><th>As of December 31, 2025</th><th></th>
          <th>As of December 31, 2024 (HKD millions)</th></tr>
        <tr><td>Cash</td><td>(</td><td>25</td><td>)</td><td>31</td></tr>
      </table>
    ''')
    current, prior = passage.cells
    assert (current.period_end, prior.period_end) == ('2025-12-31', '2024-12-31')
    assert not current.currency and prior.currency == 'HKD'
    result = check_table_observation(_proposal(current), passage)
    assert 'SIGN_SPLIT_ACROSS_SOURCE_CELLS' in result['uncertainty_reasons']
    assert result['decimal_value_as_reported'] is None
    assert result['source_statement_heading'] == 'Consolidated balance sheets'
    assert result['verification_status'] == 'PROVISIONAL_CONTEXT_UNRESOLVED'


def test_late_statement_is_not_crowded_out_by_early_summary_tables():
    earlier = '<table><tr><td>Revenue</td><td>999</td></tr></table>' * 100
    passages = _parse(earlier + '''
        <h2>Consolidated balance sheets</h2><p>HKD millions</p>
        <table><tr><th>Metric</th><th>As of December 31, 2025</th></tr>
        <tr><td>Total assets</td><td>500</td></tr></table>
    ''')
    assert passages[0].location == 'HTML table 101'
    assert passages[0].cells[0].statement_heading == 'Consolidated balance sheets'
