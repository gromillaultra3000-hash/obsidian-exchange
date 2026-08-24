<?php

namespace Tests\Feature;

use App\Filament\Resources\OrderResource;
use App\Filament\Resources\DcaScheduleResource;
use App\Filament\Resources\GiftVoucherResource;
use App\Filament\Resources\LimitOrderResource;
use App\Filament\Resources\PayoutQueueResource;
use App\Filament\Resources\ReviewResource;
use App\Filament\Resources\RiskEventResource;
use App\Filament\Resources\SellOrderResource;
use App\Filament\Resources\SupportTicketResource;
use App\Filament\Resources\SwapSessionResource;
use App\Models\BlockedUser;
use App\Models\Order;
use App\Models\Review;
use App\Models\SupportMessage;
use App\Models\SupportTicket;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class FilamentAuthorizationTest extends TestCase
{
    use RefreshDatabase;

    public function test_non_admin_session_cannot_reach_filament_dashboard(): void
    {
        $user = User::factory()->create(['is_admin' => false]);

        $response = $this->actingAs($user)->get('/admin-panel');

        $response->assertForbidden();
    }

    public function test_admin_without_enrolled_mfa_cannot_reach_filament_dashboard(): void
    {
        $admin = User::factory()->create(['is_admin' => true]);

        $response = $this->actingAs($admin)->get('/admin-panel');

        $response->assertRedirect('/admin-panel/login');
        $this->assertGuest();
    }

    public function test_orders_cannot_be_directly_edited_or_deleted(): void
    {
        $order = new Order();

        $this->assertFalse(OrderResource::canCreate());
        $this->assertFalse(OrderResource::canEdit($order));
        $this->assertFalse(OrderResource::canDelete($order));
        $this->assertFalse(OrderResource::canDeleteAny());
    }

    public function test_reviews_and_tickets_cannot_be_deleted(): void
    {
        $this->assertFalse(ReviewResource::canCreate());
        $this->assertFalse(ReviewResource::canDelete(new Review()));
        $this->assertFalse(ReviewResource::canDeleteAny());
        $this->assertFalse(SupportTicketResource::canCreate());
        $this->assertFalse(SupportTicketResource::canDelete(new SupportTicket()));
        $this->assertFalse(SupportTicketResource::canDeleteAny());
    }

    public function test_resource_models_ignore_forged_immutable_fields(): void
    {
        $review = new Review([
            'status' => 'published',
            'comment' => 'forged',
            'user_id' => 999,
        ]);
        $ticket = new SupportTicket([
            'status' => 'closed',
            'subject' => 'forged',
            'web_user_id' => 999,
        ]);
        $message = new SupportMessage([
            'message' => 'reply',
            'sender' => 'admin',
            'ticket_id' => 999,
        ]);
        $blocked = new BlockedUser([
            'user_id' => 123,
            'reason' => 'manual review',
            'blocked_at' => '2000-01-01 00:00:00',
        ]);

        $this->assertSame('published', $review->status);
        $this->assertNull($review->comment);
        $this->assertNull($review->user_id);
        $this->assertSame('closed', $ticket->status);
        $this->assertNull($ticket->subject);
        $this->assertNull($ticket->web_user_id);
        $this->assertSame('reply', $message->message);
        $this->assertNull($message->ticket_id);
        $this->assertSame(123, $blocked->user_id);
        $this->assertNull($blocked->blocked_at);
    }

    public function test_all_read_only_resources_deny_mutation_capabilities(): void
    {
        foreach ([
            OrderResource::class,
            DcaScheduleResource::class,
            GiftVoucherResource::class,
            LimitOrderResource::class,
            PayoutQueueResource::class,
            RiskEventResource::class,
            SellOrderResource::class,
            SwapSessionResource::class,
        ] as $resource) {
            $model = $resource::getModel();
            $record = new $model();

            $this->assertFalse($resource::canCreate(), "{$resource} allows create");
            $this->assertFalse($resource::canEdit($record), "{$resource} allows edit");
            $this->assertFalse($resource::canDelete($record), "{$resource} allows delete");
            $this->assertFalse($resource::canDeleteAny(), "{$resource} allows bulk delete");
        }
    }
}
