<?php

namespace App\Support;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

class AdminAudit
{
    private const SENSITIVE_FIELDS = [
        'password', 'remember_token', 'totp_secret', 'totp_last_used_timestamp',
    ];

    public static function record(string $event, Model $model): void
    {
        $actor = Auth::user();
        if (! $actor?->is_admin || ! app()->bound('request')) {
            return;
        }

        $request = request();
        $fields = $event === 'updated'
            ? array_keys($model->getChanges())
            : ($event === 'created' ? array_keys($model->getAttributes()) : []);
        $fields = array_values(array_diff($fields, self::SENSITIVE_FIELDS));
        sort($fields);

        $hashKey = (string) config('app.key');
        DB::table('admin_action_audits')->insert([
            'actor_user_id' => $actor->getAuthIdentifier(),
            'request_id' => self::requestId(),
            'event' => $event,
            'model_type' => $model::class,
            'model_key' => $model->getKey() === null ? null : (string) $model->getKey(),
            'changed_fields' => json_encode($fields, JSON_THROW_ON_ERROR),
            'route_name' => optional($request->route())->getName(),
            'method' => $request->method(),
            'ip_hash' => self::fingerprint($request->ip(), $hashKey),
            'user_agent_hash' => self::fingerprint($request->userAgent(), $hashKey),
            'created_at' => now(),
        ]);
    }

    public static function recordAction(string $event, Model $model): void
    {
        $actor = Auth::user();
        if (! $actor?->is_admin || ! app()->bound('request')) {
            return;
        }

        $request = request();
        DB::table('admin_action_audits')->insert([
            'actor_user_id' => $actor->getAuthIdentifier(),
            'request_id' => self::requestId(),
            'event' => $event,
            'model_type' => $model::class,
            'model_key' => $model->getKey() === null ? null : (string) $model->getKey(),
            'changed_fields' => '[]',
            'route_name' => optional($request->route())->getName(),
            'method' => $request->method(),
            'ip_hash' => self::fingerprint($request->ip(), (string) config('app.key')),
            'user_agent_hash' => self::fingerprint($request->userAgent(), (string) config('app.key')),
            'created_at' => now(),
        ]);
    }

    private static function requestId(): string
    {
        $request = request();
        if (! $request->attributes->has('admin_audit_request_id')) {
            $request->attributes->set('admin_audit_request_id', (string) Str::uuid());
        }

        return (string) $request->attributes->get('admin_audit_request_id');
    }

    private static function fingerprint(?string $value, string $key): ?string
    {
        return $value ? hash_hmac('sha256', $value, $key) : null;
    }
}
