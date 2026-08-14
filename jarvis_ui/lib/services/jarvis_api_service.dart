import 'dart:io';
import 'package:dio/dio.dart';

class JarvisApiService {
  final String? token;

  JarvisApiService({this.token});

  String _resolveHost(String fallback) => Platform.isAndroid ? '10.0.2.2' : fallback;

  Dio _client(String baseUrl) {
    final dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 10),
      ),
    );
    if (token != null && token!.isNotEmpty) {
      dio.options.headers['X-Jarvis-Token'] = token!;
    }
    return dio;
  }

  Future<Map<String, dynamic>> _get(String path, String host, String port) async {
    final client = _client('http://$host:$port');
    int attempt = 0;
    while (true) {
      try {
        final response = await client.get(path);
        return response.data as Map<String, dynamic>;
      } on DioException catch (e) {
        attempt++;
        if (attempt >= 2 || !_isRetryable(e)) {
          return {'status': 'error', 'message': e.toString()};
        }
        await Future.delayed(const Duration(seconds: 1));
      } catch (e) {
        return {'status': 'error', 'message': e.toString()};
      }
    }
  }

  Future<Map<String, dynamic>> getOrchestratorHealth() => _get('/health', _resolveHost('127.0.0.1'), '3000');
  Future<Map<String, dynamic>> getVoiceHealth() => _get('/health', _resolveHost('127.0.0.1'), '8080');
  Future<Map<String, dynamic>> getFlociHealth() => _get('/_localstack/health', _resolveHost('127.0.0.1'), '4566');

  Future<Map<String, dynamic>> postCommand(String prompt) async {
    final client = _client('http://${_resolveHost("127.0.0.1")}:3000');
    int attempt = 0;
    while (true) {
      try {
        final response = await client.post('/v1/execute', data: {'prompt': prompt});
        return response.data as Map<String, dynamic>;
      } on DioException catch (e) {
        attempt++;
        if (attempt >= 2 || !_isRetryable(e)) {
          return {'status': 'error', 'message': e.toString()};
        }
        await Future.delayed(const Duration(seconds: 1));
      } catch (e) {
        return {'status': 'error', 'message': e.toString()};
      }
    }
  }

  bool _isRetryable(DioException e) {
    return e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.receiveTimeout ||
        e.type == DioExceptionType.connectionError;
  }
}
