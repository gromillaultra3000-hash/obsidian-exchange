<?php

namespace App\Filament\Pages\Auth;

use App\Models\User;
use DanHarrin\LivewireRateLimiting\Exceptions\TooManyRequestsException;
use Filament\Facades\Filament;
use Filament\Forms\Components\Placeholder;
use Filament\Forms\Components\TextInput;
use Filament\Forms\Form;
use Filament\Http\Responses\Auth\Contracts\LoginResponse;
use Filament\Pages\Auth\Login as BaseLogin;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\HtmlString;
use Illuminate\Validation\ValidationException;
use PragmaRX\Google2FA\Google2FA;

class Login extends BaseLogin
{
    private const PENDING_KEY = 'admin_mfa_pending';
    private const PENDING_TTL_SECONDS = 300;

    public bool $mfaSetupRequired = false;

    public function mount(): void
    {
        parent::mount();

        $pending = session(self::PENDING_KEY);
        $this->mfaSetupRequired = $this->validPending($pending);
        if (! $this->mfaSetupRequired) {
            session()->forget(self::PENDING_KEY);
        }
    }

    protected function getForms(): array
    {
        $schema = $this->mfaSetupRequired
            ? [
                Placeholder::make('mfa_instructions')
                    ->label('Подключите двухфакторную защиту')
                    ->content(fn (): HtmlString => new HtmlString(
                        'Добавьте аккаунт в TOTP-приложение вручную. Ключ: <code>' .
                        e((string) data_get(session(self::PENDING_KEY), 'secret')) . '</code>'
                    )),
                $this->getTotpFormComponent(),
            ]
            : [
                $this->getEmailFormComponent(),
                $this->getPasswordFormComponent(),
                $this->getTotpFormComponent(),
            ];

        return [
            'form' => $this->form(
                $this->makeForm()->schema($schema)->statePath('data'),
            ),
        ];
    }

    protected function getTotpFormComponent(): TextInput
    {
        return TextInput::make('totp_code')
            ->label('Код из приложения')
            ->helperText($this->mfaSetupRequired
                ? 'Введите код после добавления показанного ключа в приложение.'
                : 'При первом входе оставьте пустым — настройка откроется после проверки пароля.')
            ->numeric()
            ->length(6)
            ->autocomplete('one-time-code')
            ->required(fn (): bool => $this->mfaSetupRequired);
    }

    public function authenticate(): ?LoginResponse
    {
        try {
            $this->rateLimit(5);
        } catch (TooManyRequestsException $exception) {
            $this->getRateLimitedNotification($exception)?->send();

            return null;
        }

        $data = $this->form->getState();
        $pending = session(self::PENDING_KEY);

        if ($this->validPending($pending)) {
            return $this->completeEnrollment($pending, (string) ($data['totp_code'] ?? ''));
        }

        session()->forget(self::PENDING_KEY);
        $user = User::query()->where('email', (string) ($data['email'] ?? ''))->first();
        if (! $user || ! Hash::check((string) ($data['password'] ?? ''), $user->password)) {
            $this->throwFailureValidationException();
        }
        if (! $user->canAccessPanel(Filament::getCurrentPanel())) {
            $this->throwFailureValidationException();
        }

        $google2fa = new Google2FA();
        if (! $user->totp_secret) {
            session()->regenerate();
            session()->put(self::PENDING_KEY, [
                'user_id' => $user->getKey(),
                'secret' => $google2fa->generateSecretKey(),
                'expires_at' => now()->addSeconds(self::PENDING_TTL_SECONDS)->timestamp,
            ]);
            $this->mfaSetupRequired = true;
            $this->form->fill(['totp_code' => '']);

            return null;
        }

        $matchedTimestamp = $google2fa->verifyKeyNewer(
            $user->totp_secret,
            (string) ($data['totp_code'] ?? ''),
            $user->totp_last_used_timestamp,
            1,
        );
        if ($matchedTimestamp === false || ! $this->claimTotpTimestamp($user, (int) $matchedTimestamp)) {
            $this->throwTotpValidationException();
        }

        return $this->finishLogin($user);
    }

    private function completeEnrollment(array $pending, string $code): ?LoginResponse
    {
        $user = User::query()->find($pending['user_id']);
        if (! $user || ! $user->canAccessPanel(Filament::getCurrentPanel())) {
            session()->forget(self::PENDING_KEY);
            $this->throwFailureValidationException();
        }

        $google2fa = new Google2FA();
        $matchedTimestamp = $google2fa->verifyKey((string) $pending['secret'], $code, 1);
        if ($matchedTimestamp === false) {
            $this->throwTotpValidationException();
        }

        $user->forceFill([
            'totp_secret' => (string) $pending['secret'],
            'totp_enabled_at' => now(),
            'totp_last_used_timestamp' => (int) $matchedTimestamp,
        ])->save();
        session()->forget(self::PENDING_KEY);

        return $this->finishLogin($user);
    }

    private function finishLogin(User $user): LoginResponse
    {
        Filament::auth()->login($user, false);
        session()->regenerate();

        return app(LoginResponse::class);
    }

    private function validPending(mixed $pending): bool
    {
        return is_array($pending)
            && isset($pending['user_id'], $pending['secret'], $pending['expires_at'])
            && is_numeric($pending['expires_at'])
            && (int) $pending['expires_at'] >= now()->timestamp;
    }

    private function claimTotpTimestamp(User $user, int $timestamp): bool
    {
        // Atomic compare-and-set: two concurrent requests with the same TOTP
        // can verify cryptographically, but only one may claim its time step.
        return User::query()
            ->whereKey($user->getKey())
            ->where(function ($query) use ($timestamp): void {
                $query->whereNull('totp_last_used_timestamp')
                    ->orWhere('totp_last_used_timestamp', '<', $timestamp);
            })
            ->update(['totp_last_used_timestamp' => $timestamp]) === 1;
    }

    private function throwTotpValidationException(): never
    {
        throw ValidationException::withMessages([
            'data.totp_code' => 'Неверный или просроченный код двухфакторной защиты.',
        ]);
    }
}
