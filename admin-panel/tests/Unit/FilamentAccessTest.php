<?php

namespace Tests\Unit;

use App\Models\User;
use Filament\Panel;
use PHPUnit\Framework\TestCase;

class FilamentAccessTest extends TestCase
{
    public function test_panel_access_is_denied_without_admin_role(): void
    {
        $user = (new User())->forceFill([
            'email' => 'admin@example.test',
            'is_admin' => false,
        ]);

        $this->assertFalse($user->canAccessPanel(Panel::make()));
    }

    public function test_panel_access_requires_admin_role(): void
    {
        $user = (new User())->forceFill(['is_admin' => true]);

        $this->assertTrue($user->canAccessPanel(Panel::make()));
    }

    public function test_admin_role_cannot_be_mass_assigned(): void
    {
        $user = new User(['is_admin' => true]);

        $this->assertFalse((bool) $user->is_admin);
    }

    public function test_totp_secret_is_hidden_and_not_mass_assignable(): void
    {
        $user = new User(['totp_secret' => 'attacker-controlled']);

        $this->assertNull($user->totp_secret);
        $this->assertContains('totp_secret', $user->getHidden());
    }
}
