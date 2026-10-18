import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() => runApp(const NanzaMobileApp());

class NanzaMobileApp extends StatelessWidget {
  const NanzaMobileApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Nanza',
        theme: ThemeData(colorSchemeSeed: const Color(0xff0a1931), useMaterial3: true),
        home: const LoginPage(),
      );
}

class NanzaApi {
  NanzaApi(this.baseUrl, {this.token, this.companyId, this.fiscalYear});

  final String baseUrl;
  final String? token;
  final String? companyId;
  final int? fiscalYear;

  Uri _uri(String path) => Uri.parse('${baseUrl.replaceFirst(RegExp(r'/+$'), '')}$path');

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        if (companyId != null) 'X-Company-ID': companyId!,
        if (fiscalYear != null) 'X-Fiscal-Year': '$fiscalYear',
      };

  Future<dynamic> get(String path) async {
    final response = await http.get(_uri(path), headers: _headers);
    return _decode(response);
  }

  Future<dynamic> post(String path, Map<String, dynamic> body) async {
    final response = await http.post(_uri(path), headers: _headers, body: jsonEncode(body));
    return _decode(response);
  }

  dynamic _decode(http.Response response) {
    final dynamic value;
    try {
      value = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw Exception('Server returned an invalid response (${response.statusCode}).');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiFailure(response.statusCode,
          value is Map ? '${value['error'] ?? 'Request failed.'}' : 'Request failed.');
    }
    return value;
  }
}

class ApiFailure implements Exception {
  ApiFailure(this.statusCode, this.message);
  final int statusCode;
  final String message;

  @override
  String toString() => message;
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _url = TextEditingController(text: 'https://');
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;

  Future<void> _login() async {
    setState(() => _busy = true);
    try {
      final base = _url.text.trim().replaceFirst(RegExp(r'/+$'), '');
      final api = NanzaApi(base);
      final result = await api.post('/api/login', {
        'username': _username.text.trim(),
        'password': _password.text,
      }) as Map<String, dynamic>;
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => CompanyPage(baseUrl: base, token: result['token'] as String),
      ));
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showError(Object error) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
  }

  @override
  void dispose() {
    _url.dispose();
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Nanza sign in')),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          TextField(controller: _url, decoration: const InputDecoration(labelText: 'Server URL')),
          TextField(controller: _username, decoration: const InputDecoration(labelText: 'Username')),
          TextField(
            controller: _password,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Password'),
            onSubmitted: (_) => _login(),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy ? null : _login,
            child: Text(_busy ? 'Signing in…' : 'Sign in'),
          ),
        ]),
      );
}

class CompanyPage extends StatefulWidget {
  const CompanyPage({super.key, required this.baseUrl, required this.token});
  final String baseUrl;
  final String token;

  @override
  State<CompanyPage> createState() => _CompanyPageState();
}

class _CompanyPageState extends State<CompanyPage> {
  List<Map<String, dynamic>> _companies = [];
  String? _company;
  int _year = DateTime.now().year;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _loadCompanies();
  }

  Future<void> _loadCompanies() async {
    try {
      final result = await NanzaApi(widget.baseUrl, token: widget.token).get('/api/companies');
      final items = (result['items'] as List).cast<Map<String, dynamic>>();
      if (!mounted) return;
      setState(() {
        _companies = items;
        _company = items.isEmpty ? null : '${items.first['id']}';
        final years = items.isEmpty ? null : items.first['years'];
        if (years is List && years.isNotEmpty) {
          _year = int.tryParse('${years.last is Map ? years.last['year'] : years.last}') ?? _year;
        }
        _busy = false;
      });
    } catch (error) {
      if (mounted) {
        setState(() => _busy = false);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  void _open() {
    if (_company == null) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(
      builder: (_) => HomePage(
        baseUrl: widget.baseUrl,
        token: widget.token,
        companyId: _company!,
        fiscalYear: _year,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Select company')),
        body: Padding(
          padding: const EdgeInsets.all(20),
          child: _busy
              ? const Center(child: CircularProgressIndicator())
              : Column(mainAxisSize: MainAxisSize.min, children: [
                  DropdownButtonFormField<String>(
                    value: _company,
                    items: _companies
                        .map((item) => DropdownMenuItem(
                              value: '${item['id']}',
                              child: Text('${item['name'] ?? item['company_name'] ?? item['id']}'),
                            ))
                        .toList(),
                    onChanged: (value) => setState(() => _company = value),
                    decoration: const InputDecoration(labelText: 'Company'),
                  ),
                  TextFormField(
                    initialValue: '$_year',
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Fiscal year'),
                    onChanged: (value) => _year = int.tryParse(value) ?? _year,
                  ),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _open, child: const Text('Continue')),
                ]),
        ),
      );
}

class HomePage extends StatefulWidget {
  const HomePage({
    super.key,
    required this.baseUrl,
    required this.token,
    required this.companyId,
    required this.fiscalYear,
  });
  final String baseUrl;
  final String token;
  final String companyId;
  final int fiscalYear;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late final NanzaApi _api = NanzaApi(
    widget.baseUrl,
    token: widget.token,
    companyId: widget.companyId,
    fiscalYear: widget.fiscalYear,
  );
  final _prefsFuture = SharedPreferences.getInstance();
  String get _approvalsCacheKey => 'pending_approvals_${widget.companyId}_${widget.fiscalYear}';
  String get _actionsQueueKey => 'pending_actions_${widget.companyId}_${widget.fiscalYear}';
  List<Map<String, dynamic>> _approvals = [];
  List<Map<String, dynamic>> _cashRows = [];
  double _overdueAr = 0;
  double _overdueAp = 0;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([
        _api.get('/api/approvals'),
        _api.get('/api/reports/cash-forecast/13-week'),
        _api.get('/api/aging?kind=sale'),
        _api.get('/api/aging?kind=purchase'),
      ]);
      final approvals = (results[0]['items'] as List).cast<Map<String, dynamic>>();
      final cashRows = (results[1]['rows'] as List).cast<Map<String, dynamic>>();
      double overdue(List<dynamic> rows) => rows
          .where((row) => (row['days_overdue'] as num? ?? 0) > 0)
          .fold<double>(0, (sum, row) => sum + ((row['outstanding'] as num?)?.toDouble() ?? 0));
      final prefs = await _prefsFuture;
      await prefs.setString(_approvalsCacheKey, jsonEncode(approvals));
      if (!mounted) return;
      setState(() {
        _approvals = approvals;
        _cashRows = cashRows;
        _overdueAr = overdue(results[2]['items'] as List);
        _overdueAp = overdue(results[3]['items'] as List);
      });
      final hadQueuedActions = await _syncQueuedActions();
      if (hadQueuedActions) {
        final updated = await _api.get('/api/approvals');
        final current = (updated['items'] as List).cast<Map<String, dynamic>>();
        await prefs.setString(_approvalsCacheKey, jsonEncode(current));
        if (mounted) setState(() => _approvals = current);
      }
    } catch (error) {
      final prefs = await _prefsFuture;
      final cached = prefs.getString(_approvalsCacheKey);
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _approvals = cached == null
            ? []
            : (jsonDecode(cached) as List).cast<Map<String, dynamic>>();
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<bool> _syncQueuedActions() async {
    final prefs = await _prefsFuture;
    final queue = (jsonDecode(prefs.getString(_actionsQueueKey) ?? '[]') as List)
        .cast<Map<String, dynamic>>();
    final failures = <Map<String, dynamic>>[];
    var attempted = false;
    for (final action in queue) {
      try {
        attempted = true;
        await _api.post(
          action['action'] == 'approve' ? '/api/approvals/approve' : '/api/approvals/reject',
          action['payload'] as Map<String, dynamic>,
        );
      } on ApiFailure catch (error) {
        if (error.statusCode >= 500) {
          failures.add(action);
        } else if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Queued approval was not accepted: $error')),
          );
        }
      } catch (_) {
        failures.add(action);
      }
    }
    await prefs.setString(_actionsQueueKey, jsonEncode(failures));
    return attempted;
  }

  Future<void> _decide(Map<String, dynamic> item, bool approve) async {
    final reason = approve ? null : await _rejectionReason();
    if (!approve && (reason == null || reason.trim().isEmpty)) return;
    final invoice = item['kind'] == 'invoices';
    final payload = <String, dynamic>{
      if (invoice) 'entry_ids': <int>[], if (invoice) 'invoice_ids': [item['id']],
      if (!invoice) 'entry_ids': [item['id']], if (!invoice) 'invoice_ids': <int>[],
      if (!approve) 'reason': reason,
    };
    final action = <String, dynamic>{
      'action': approve ? 'approve' : 'reject',
      'payload': payload,
    };
    try {
      await _api.post(approve ? '/api/approvals/approve' : '/api/approvals/reject', payload);
      await _refresh();
    } on ApiFailure catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    } catch (error) {
      final prefs = await _prefsFuture;
      final queue = (jsonDecode(prefs.getString(_actionsQueueKey) ?? '[]') as List).toList();
      queue.add(action);
      await prefs.setString(_actionsQueueKey, jsonEncode(queue));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Saved offline; will retry on refresh. $error')),
        );
      }
    }
  }

  Future<String?> _rejectionReason() async {
    final controller = TextEditingController();
    return showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Reject document'),
        content: TextField(controller: controller, decoration: const InputDecoration(labelText: 'Reason')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, controller.text), child: const Text('Reject')),
        ],
      ),
    );
  }

  Future<void> _askAccountant() async {
    final question = TextEditingController();
    final text = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('AI Accountant'),
        content: TextField(controller: question, autofocus: true, decoration: const InputDecoration(hintText: 'Ask in English, Arabic, or French')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, question.text), child: const Text('Ask')),
        ],
      ),
    );
    if (text == null || text.trim().isEmpty) return;
    try {
      final result = await _api.post('/api/ai_chat', {'question': text});
      if (mounted) {
        showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('AI Accountant'),
            content: SingleChildScrollView(child: Text('${result['answer']['message']}\n\nSources: ${result['answer']['sources'].length}')),
            actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
          ),
        );
      }
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  Future<void> _captureReceipt() async {
    try {
      final image = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 80);
      if (image == null) return;
      if (!mounted) return;
      final details = await showDialog<Map<String, String>>(
        context: context,
        builder: (context) {
          final description = TextEditingController();
          final amount = TextEditingController();
          final currency = TextEditingController(text: 'USD');
          return AlertDialog(
            title: const Text('Expense claim'),
            content: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: description, decoration: const InputDecoration(labelText: 'Description')),
              TextField(controller: amount, keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(labelText: 'Amount')),
              TextField(controller: currency, textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(labelText: 'Currency')),
            ]),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
              FilledButton(onPressed: () => Navigator.pop(context, {
                'description': description.text.trim(),
                'amount': amount.text.trim(),
                'currency': currency.text.trim().toUpperCase(),
              }), child: const Text('Save claim')),
            ],
          );
        },
      );
      if (details == null) return;
      final amount = double.tryParse(details['amount'] ?? '');
      if (details['description']!.isEmpty || amount == null || amount <= 0 ||
          !RegExp(r'^[A-Z]{3}$').hasMatch(details['currency'] ?? '')) {
        throw Exception('Enter a description, positive amount, and three-letter currency code.');
      }
      final file = File(image.path);
      final content = base64Encode(await file.readAsBytes());
      final date = DateTime.now().toIso8601String().substring(0, 10);
      final created = await _api.post('/api/expenses', {
        'expense_date': date,
        'description': details['description'],
        'currency': details['currency'],
        'subtotal': amount.toString(),
        'vat': '0',
      });
      final expenseId = created['expense_id'];
      final queued = await _api.post('/api/ocr/queue', {
        'expense_id': expenseId,
        'file_name': image.name,
        'mime_type': 'image/jpeg',
        'content': content,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(
            'Expense claim $expenseId saved; receipt queued for OCR (${queued['queue_id']}).')),
        );
      }
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final currencyRows = _cashRows.where((row) => row['currency'] == 'USD').toList();
    final cash = currencyRows.isEmpty ? 0.0 : (currencyRows.first['opening'] as num?)?.toDouble() ?? 0;
    return Scaffold(
      appBar: AppBar(
        title: Text('Nanza · FY ${widget.fiscalYear}'),
        actions: [IconButton(onPressed: _loading ? null : _refresh, icon: const Icon(Icons.refresh))],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _captureReceipt,
        icon: const Icon(Icons.camera_alt),
        label: const Text('Capture'),
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          if (_error != null) Text('Offline/refresh error: $_error', style: const TextStyle(color: Colors.red)),
          Wrap(spacing: 10, runSpacing: 10, children: [
            _metric('Cash balance (USD)', cash),
            _metric('Overdue AR', _overdueAr),
            _metric('Overdue AP', _overdueAp),
            _metric('Pending approvals', _approvals.length.toDouble(), decimals: 0),
          ]),
          const SizedBox(height: 12),
          FilledButton.tonalIcon(onPressed: _askAccountant, icon: const Icon(Icons.chat), label: const Text('AI Accountant')),
          const SizedBox(height: 16),
          Text('Pending approvals', style: Theme.of(context).textTheme.titleLarge),
          if (_approvals.isEmpty) const ListTile(title: Text('No pending approvals')),
          ..._approvals.map((item) => Card(
                child: ListTile(
                  title: Text('${item['number']} · ${item['kind']}'),
                  subtitle: Text('${item['description']}\n${item['date']} · ${item['currency']} ${item['amount']} · ${item['prepared_by']}'),
                  isThreeLine: true,
                  trailing: PopupMenuButton<String>(
                    onSelected: (value) => _decide(item, value == 'approve'),
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'approve', child: Text('Approve')),
                      PopupMenuItem(value: 'reject', child: Text('Reject')),
                    ],
                  ),
                ),
              )),
          const SizedBox(height: 12),
          Text('13-week forecast', style: Theme.of(context).textTheme.titleLarge),
          ...currencyRows.take(13).map((row) => ListTile(
                title: Text('Week ${row['week']} · ${row['from']}'),
                subtitle: Text('In ${row['cash_in']} · Out ${row['cash_out']} · Net ${row['net']}'),
                trailing: Text('${row['closing']} ${row['currency']}'),
              )),
        ]),
      ),
    );
  }

  Widget _metric(String title, double value, {int decimals = 2}) => SizedBox(
        width: 160,
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title),
              const SizedBox(height: 6),
              Text(value.toStringAsFixed(decimals), style: Theme.of(context).textTheme.titleMedium),
            ]),
          ),
        ),
      );
}
