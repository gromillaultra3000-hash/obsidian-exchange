<?php

namespace Tests\Feature;

use App\Filament\Pages\Auth\Login;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use ReflectionMethod;
use Tests\TestCase;

class TotpReplayGuardTest extends TestCase
{
    use RefreshDatabase;

    public function test_only_one_request_can_claim_a_totp_time_step(): void
    {
        $user = User::factory()->create(['is_admin' => true]);
        $claim = new ReflectionMethod(Login::class, 'claimTotpTimestamp');
        $page = new Login();

        $this->assertTrue($claim->invoke($page, $user, 123456));
        $this->assertFalse($claim->invoke($page, $user->fresh(), 123456));
        $this->assertTrue($claim->invoke($page, $user->fresh(), 123457));
        $this->assertSame(123457, $user->fresh()->totp_last_used_timestamp);
    }
}
