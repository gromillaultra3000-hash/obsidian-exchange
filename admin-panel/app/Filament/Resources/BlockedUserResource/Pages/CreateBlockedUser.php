<?php

namespace App\Filament\Resources\BlockedUserResource\Pages;

use App\Filament\Resources\BlockedUserResource;
use Filament\Actions;
use Filament\Resources\Pages\CreateRecord;

class CreateBlockedUser extends CreateRecord
{
    protected static string $resource = BlockedUserResource::class;

    protected function mutateFormDataBeforeCreate(array $data): array
    {
        return [
            'user_id' => $data['user_id'],
            'reason' => $data['reason'] ?? 'admin block',
        ];
    }
}
